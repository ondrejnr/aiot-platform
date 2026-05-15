pipeline {
  agent {
    kubernetes {
      defaultContainer "git"
      yaml """
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: jenkins
  securityContext:
    runAsUser: 1000
    fsGroup: 1000
  restartPolicy: Never
  containers:
    - name: git
      image: alpine/git:2.49.1
      command:
        - cat
      tty: true
    - name: helm
      image: alpine/helm:3.17.3
      command:
        - cat
      tty: true
    - name: tofu
      image: ghcr.io/opentofu/opentofu:1.9.1
      command:
        - cat
      tty: true
    - name: flux
      image: ghcr.io/fluxcd/flux-cli:v2.6.4
      command:
        - cat
      tty: true
"""
    }
  }

  options {
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: "20"))
  }

  stages {
    stage("Checkout from Gitea") {
      steps {
        checkout scm
      }
    }

    stage("OpenTofu validate/plan") {
      steps {
        container("tofu") {
          dir("terraform/observability-gitops") {
            sh "tofu fmt -check -recursive"
            sh "tofu init -backend=false"
            sh "tofu validate"
            sh "tofu plan -input=false -lock=false -out=tfplan"
            sh "tofu show -no-color tfplan | sed -n '1,160p'"
          }
        }
      }
    }

    stage("Helm validate GitOps charts") {
      steps {
        container("helm") {
          sh """
set -eu
helm dependency build apps/loki
helm lint apps/loki
helm template ci-loki apps/loki >/tmp/loki.yaml
helm dependency build apps/alloy
helm lint apps/alloy
helm template ci-alloy apps/alloy >/tmp/alloy.yaml
helm dependency build apps/signoz
helm lint apps/signoz
helm template ci-signoz apps/signoz >/tmp/signoz.yaml
helm dependency build apps/k8s-infra
helm lint apps/k8s-infra
helm template ci-k8s-infra apps/k8s-infra >/tmp/k8s-infra.yaml
"""
        }
      }
    }

    stage("Flux reconcile") {
      steps {
        container("flux") {
          sh """
set -eu
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization flux-system -n flux-system
flux get hr -A | grep -E "loki|alloy|signoz|k8s-infra"
"""
        }
      }
    }
  }
}
