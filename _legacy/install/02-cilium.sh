#!/bin/bash
# ============================================================================
# 02-cilium.sh  — Install Cilium 1.16.6 CNI.
# ----------------------------------------------------------------------------
# Uses values from cluster-wide/helm-values/kube-system_cilium.yaml.
# kubeProxyReplacement=true means kube-proxy must NOT run; if you used
# kubeadm with --skip-phases=addon/kube-proxy that's already handled.
# Otherwise: kubectl -n kube-system delete ds kube-proxy && kubectl -n kube-system delete cm kube-proxy
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VALUES="${REPO_ROOT}/cluster-wide/helm-values/kube-system_cilium.yaml"

CILIUM_VERSION="${CILIUM_VERSION:-1.16.6}"

helm repo add cilium https://helm.cilium.io >/dev/null 2>&1 || true
helm repo update cilium >/dev/null

# Remove kube-proxy (Cilium will replace it)
kubectl -n kube-system delete ds kube-proxy --ignore-not-found
kubectl -n kube-system delete cm kube-proxy --ignore-not-found
# Flush legacy kube-proxy iptables rules on all nodes (run manually per node):
#   iptables-save | grep -v KUBE | iptables-restore

helm upgrade --install cilium cilium/cilium \
  --version "${CILIUM_VERSION}" \
  --namespace kube-system \
  -f "${VALUES}"

echo "[02] Cilium installed. Waiting for DaemonSet..."
kubectl -n kube-system rollout status ds/cilium

echo "[02] Verifying:"
kubectl -n kube-system get pods -l k8s-app=cilium -o wide
kubectl -n kube-system exec -t ds/cilium -- cilium status --brief || true
