terraform {
  required_version = ">= 1.8.0"
}

locals {
  cluster_name = "hetzner-new"

  gitops_source = {
    provider = "gitea"
    url      = "http://gitea-http.gitea.svc.cluster.local:3000/aiot-iac/aiot-platform.git"
    branch   = "main"
  }

  observability_logging = {
    namespace      = "observability-logs"
    retention_days = 7
    flux_releases  = ["loki", "alloy", "signoz", "k8s-infra"]
  }

  required_files = [
    "apps/loki/Chart.yaml",
    "apps/loki/values.yaml",
    "apps/alloy/Chart.yaml",
    "apps/alloy/values.yaml",
    "apps/signoz/templates/log-retention-7d-job.yaml",
    "apps/k8s-infra/values.yaml",
    "flux/clusters/hetzner-new/apps/loki.yaml",
    "flux/clusters/hetzner-new/apps/alloy.yaml",
    "flux/clusters/hetzner-new/apps/signoz.yaml",
    "flux/clusters/hetzner-new/apps/k8s-infra.yaml",
    "flux/clusters/hetzner-new/apps/jenkins-flux-rbac.yaml",
    "flux/clusters/hetzner-new/flux-system/gotk-sync.yaml",
    "apps/jenkins/values.yaml",
    "Jenkinsfile",
  ]
}

check "gitops_files_exist" {
  assert {
    condition     = alltrue([for file_path in local.required_files : fileexists("${path.module}/../../${file_path}")])
    error_message = "One or more required observability GitOps/Jenkins files are missing."
  }
}

resource "terraform_data" "observability_logging_gitops" {
  input = {
    cluster               = local.cluster_name
    source                = local.gitops_source
    observability_logging = local.observability_logging
  }
}

output "observability_logging_gitops" {
  value = terraform_data.observability_logging_gitops.input
}
