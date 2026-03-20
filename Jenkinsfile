pipeline {
  agent { label 'k8s-agent' }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Install kubectl') {
      steps {
        sh '''
          set -e
          rm -f /tmp/kubectl
          curl -L -o /tmp/kubectl https://dl.k8s.io/release/v1.30.10/bin/linux/amd64/kubectl
          chmod +x /tmp/kubectl
          /tmp/kubectl version --client
        '''
      }
    }

    stage('Compare repo vs cluster') {
      steps {
        sh '''
          set +e
          /tmp/kubectl auth can-i get pods --all-namespaces
          find k8s -type f \( -name '*.yaml' -o -name '*.yml' \) | sort > manifest-list.txt
          cat manifest-list.txt
          : > cluster-diff.txt
          xargs -r -a manifest-list.txt -n1 /tmp/kubectl diff -f >> cluster-diff.txt 2>&1
          cat cluster-diff.txt
          exit 0
        '''
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'manifest-list.txt,cluster-diff.txt', allowEmptyArchive: true
    }
  }
}
