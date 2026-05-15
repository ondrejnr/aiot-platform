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
mkdir -p /tmp/helm/cache /tmp/helm/config /tmp/helm/data
export HELM_CACHE_HOME=/tmp/helm/cache
export HELM_CONFIG_HOME=/tmp/helm/config
export HELM_DATA_HOME=/tmp/helm/data
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

    stage("Observability self-check") {
      steps {
        container("flux") {
          sh '''
set -eu

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

LOKI_URL="http://loki-gateway.observability-logs.svc.cluster.local"
CLICKHOUSE_SELECTOR="clickhouse.altinity.com/chi=signoz-clickhouse,clickhouse.altinity.com/ready=yes"

echo "Checking Alloy DaemonSet readiness..."
ALLOY_DESIRED="$(kubectl -n observability-logs get ds alloy -o jsonpath='{.status.desiredNumberScheduled}')"
ALLOY_READY="$(kubectl -n observability-logs get ds alloy -o jsonpath='{.status.numberReady}')"
echo "Alloy ready pods: ${ALLOY_READY}/${ALLOY_DESIRED}"
[ "${ALLOY_DESIRED}" -gt 0 ] || fail "Alloy desired pod count is zero"
[ "${ALLOY_READY}" = "${ALLOY_DESIRED}" ] || fail "Alloy is not ready on all scheduled nodes"

echo "Checking SigNoz k8s-infra agent readiness..."
K8S_INFRA_DESIRED="$(kubectl -n signoz get ds k8s-infra-otel-agent -o jsonpath='{.status.desiredNumberScheduled}')"
K8S_INFRA_READY="$(kubectl -n signoz get ds k8s-infra-otel-agent -o jsonpath='{.status.numberReady}')"
echo "k8s-infra ready pods: ${K8S_INFRA_READY}/${K8S_INFRA_DESIRED}"
[ "${K8S_INFRA_DESIRED}" -gt 0 ] || fail "k8s-infra desired pod count is zero"
[ "${K8S_INFRA_READY}" = "${K8S_INFRA_DESIRED}" ] || fail "k8s-infra agent is not ready on all scheduled nodes"

echo "Checking Loki API and recent aiot logs collected by Alloy..."
wget -qO- "${LOKI_URL}/loki/api/v1/labels" >/tmp/loki-labels.json
grep -q '"namespace"' /tmp/loki-labels.json || fail "Loki labels endpoint does not expose namespace label"
wget -qO- "${LOKI_URL}/loki/api/v1/query_range?query=%7Bsource%3D%22alloy%22%2Cnamespace%3D%22aiot%22%7D" >/tmp/loki-aiot.json
if grep -Fq '"result":[]' /tmp/loki-aiot.json; then
  fail "Loki has no logs for namespace aiot with source=alloy"
fi
grep -q '"source":"alloy"' /tmp/loki-aiot.json || fail "Loki query did not return Alloy-sourced logs"
grep -q '"namespace":"aiot"' /tmp/loki-aiot.json || fail "Loki query did not return aiot namespace logs"
echo "Loki check passed."

echo "Checking SigNoz ClickHouse recent logs and 7-day retention..."
CLICKHOUSE_POD="$(kubectl -n signoz get pod -l "${CLICKHOUSE_SELECTOR}" -o jsonpath='{.items[0].metadata.name}')"
[ -n "${CLICKHOUSE_POD}" ] || fail "No ready SigNoz ClickHouse pod found"
echo "Using ClickHouse pod: ${CLICKHOUSE_POD}"
SIGNOZ_RECENT_LOGS="$(kubectl -n signoz exec "${CLICKHOUSE_POD}" -c clickhouse -- clickhouse-client -q "SELECT count() FROM signoz_logs.logs_v2 WHERE timestamp >= toUnixTimestamp64Nano(now64(9) - INTERVAL 10 MINUTE)")"
echo "SigNoz logs in last 10 minutes: ${SIGNOZ_RECENT_LOGS}"
[ "${SIGNOZ_RECENT_LOGS}" -gt 0 ] || fail "SigNoz has no logs in the last 10 minutes"
kubectl -n signoz exec "${CLICKHOUSE_POD}" -c clickhouse -- clickhouse-client -q "SHOW CREATE TABLE signoz_logs.logs_v2" >/tmp/signoz-logs-ddl.txt
grep -q '_retention_days.*DEFAULT 7' /tmp/signoz-logs-ddl.txt || fail "SigNoz logs_v2 _retention_days default is not 7"
grep -q 'toIntervalDay(7)' /tmp/signoz-logs-ddl.txt || fail "SigNoz logs_v2 TTL is not 7 days"
echo "SigNoz check passed."

echo "Observability self-check passed."
'''
        }
      }
    }
  }
}
