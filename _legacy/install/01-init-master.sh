#!/bin/bash
# ============================================================================
# 01-init-master.sh  — Initialize the control-plane on the first master.
# ----------------------------------------------------------------------------
# Uses infra/kubeadm-config.yaml as authoritative source. After kubeadm init
# completes, prints the `kubeadm join` token for workers.
# Pod CIDR: 10.245.0.0/16 (Cilium). Service CIDR: 10.96.0.0/12 (default).
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KUBEADM_CFG="${REPO_ROOT}/infra/kubeadm-config.yaml"

[ -f "$KUBEADM_CFG" ] || { echo "Missing $KUBEADM_CFG"; exit 1; }

echo "[01] kubeadm init using $KUBEADM_CFG"
kubeadm init --config="$KUBEADM_CFG" --upload-certs

# kubeconfig for current user
mkdir -p "$HOME/.kube"
cp -f /etc/kubernetes/admin.conf "$HOME/.kube/config"
chown "$(id -u):$(id -g)" "$HOME/.kube/config"

# Also export for root via /etc/kubernetes/admin.conf
export KUBECONFIG=/etc/kubernetes/admin.conf

echo "[01] Cluster initialized. Nodes:"
kubectl get nodes -o wide

echo
echo "================================================================"
echo "Run on EVERY worker (output below):"
echo "================================================================"
kubeadm token create --print-join-command
