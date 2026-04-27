#!/bin/bash
# bootstrap/01-kubeadm-init.sh — initialize the first master node.
# Reads infra/kubeadm-config.yaml. Master skips kube-proxy (Cilium replaces it).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG="${REPO_ROOT}/infra/kubeadm-config.yaml"

[ -f "$CFG" ] || { echo "Missing $CFG"; exit 1; }

# Detect primary IP (advertiseAddress)
PRIMARY_IP="${PRIMARY_IP:-$(ip route get 1.1.1.1 | awk '{print $7; exit}')}"
echo "[01] PRIMARY_IP=${PRIMARY_IP}"

# Make a working copy with substituted advertiseAddress
WORK="/tmp/kubeadm-config.runtime.yaml"
sed "s|advertiseAddress: 0.0.0.0|advertiseAddress: ${PRIMARY_IP}|" "$CFG" > "$WORK"

echo "[01] kubeadm init using $WORK"
kubeadm init --config="$WORK" --upload-certs --skip-phases=addon/kube-proxy

# kubeconfig for invoking user
mkdir -p "${HOME}/.kube"
cp -f /etc/kubernetes/admin.conf "${HOME}/.kube/config"
[ -n "${SUDO_USER:-}" ] && {
  USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
  install -d -m 0700 -o "$SUDO_USER" -g "$SUDO_USER" "${USER_HOME}/.kube"
  install -m 0600 -o "$SUDO_USER" -g "$SUDO_USER" /etc/kubernetes/admin.conf "${USER_HOME}/.kube/config"
}

export KUBECONFIG=/etc/kubernetes/admin.conf
echo "[01] Cluster up. Nodes:"
kubectl get nodes

echo
echo "================================================================"
echo "Run on EVERY worker:"
echo "================================================================"
kubeadm token create --print-join-command
echo
echo "Save the token output. Workers will report NotReady until step 02 (Cilium)."
