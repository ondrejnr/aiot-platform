#!/bin/bash
# bootstrap/02-flannel.sh — install Flannel CNI (replaces Cilium since 2026-04-27).
# Run on master after all workers have joined.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FLANNEL_VERSION="${FLANNEL_VERSION:-v0.27.4}"
MANIFEST_URL="https://github.com/flannel-io/flannel/releases/download/${FLANNEL_VERSION}/kube-flannel.yml"

echo "[02] Applying Flannel ${FLANNEL_VERSION}"
kubectl apply -f "$MANIFEST_URL"

echo "[02] Patching DaemonSet with memory limits + KUBERNETES_SERVICE_HOST"
# Detect kube-apiserver IP (master internal IP) so OCI nodes (via WireGuard) can
# bypass the kube-proxy ClusterIP DNAT — see infra/cni-flannel.conflist comments.
APISERVER_IP="${APISERVER_IP:-$(kubectl -n default get endpoints kubernetes \
  -o jsonpath='{.subsets[0].addresses[0].ip}')}"
APISERVER_PORT="${APISERVER_PORT:-6443}"

kubectl -n kube-flannel patch ds kube-flannel-ds --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources","value":{"requests":{"cpu":"100m","memory":"50Mi"},"limits":{"memory":"200Mi"}}},
  {"op":"replace","path":"/spec/template/spec/initContainers/0/resources","value":{"requests":{"cpu":"50m","memory":"32Mi"},"limits":{"memory":"100Mi"}}},
  {"op":"replace","path":"/spec/template/spec/initContainers/1/resources","value":{"requests":{"cpu":"50m","memory":"32Mi"},"limits":{"memory":"100Mi"}}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KUBERNETES_SERVICE_HOST","value":"'"$APISERVER_IP"'"}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KUBERNETES_SERVICE_PORT","value":"'"$APISERVER_PORT"'"}}
]'

echo "[02] Waiting for Flannel DaemonSet..."
kubectl -n kube-flannel rollout status ds/kube-flannel-ds --timeout=300s

echo "[02] Flannel pods:"
kubectl -n kube-flannel get pods -o wide
kubectl get nodes -o wide
