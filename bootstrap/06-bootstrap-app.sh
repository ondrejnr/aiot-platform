#!/bin/bash
# bootstrap/06-bootstrap-app.sh — apply the ArgoCD root Application.
# After this runs, ArgoCD takes over the cluster and reconciles everything
# defined under argocd/ from this Git repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${REPO_ROOT}/argocd/bootstrap/root-app.yaml"

[ -f "$ROOT" ] || { echo "Missing $ROOT"; exit 1; }

kubectl apply -f "$ROOT"

echo "[06] Root Application applied. Watch sync status:"
echo "  kubectl -n argocd get applications -w"
echo
echo "  argocd login argocd.aiot.local --username admin --password <see step 05>"
echo "  argocd app list"
