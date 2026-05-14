# Observability GitOps OpenTofu check

This OpenTofu root is intentionally lightweight. Kubernetes resources are still owned by Flux.
The Jenkins pipeline uses this root to validate the GitOps contract for Loki, Alloy, SigNoz, and k8s-infra before it asks Flux to reconcile.
