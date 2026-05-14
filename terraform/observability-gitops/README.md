# Observability GitOps OpenTofu check

This OpenTofu root is intentionally lightweight. Kubernetes resources are still owned by Flux.
Jenkins job `aiot-platform-gitops` uses this root to validate the GitOps contract for Loki, Alloy, SigNoz, and k8s-infra before it asks Flux to reconcile the Gitea source.
