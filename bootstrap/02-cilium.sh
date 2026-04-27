#!/bin/bash
# bootstrap/02-cilium.sh — install Cilium CNI with full production values.
# Run on master after all workers have joined.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CILIUM_VERSION="${CILIUM_VERSION:-1.16.6}"
VALUES="${REPO_ROOT}/cluster-wide/helm-values/kube-system_cilium.yaml"

[ -f "$VALUES" ] || { echo "Missing $VALUES"; exit 1; }

helm repo add cilium https://helm.cilium.io >/dev/null 2>&1 || true
helm repo update cilium >/dev/null

helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version "$CILIUM_VERSION" \
  -f "$VALUES" \
  --set kubeProxyReplacement=true

echo "[02] Waiting for Cilium DaemonSet..."
kubectl -n kube-system rollout status ds/cilium

echo "[02] Cilium status:"
kubectl -n kube-system exec ds/cilium -- cilium status --brief || true
kubectl get nodes -o wide
