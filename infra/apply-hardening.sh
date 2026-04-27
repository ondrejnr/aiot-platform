#!/bin/bash
# Bootstrap hardening for fresh clusters. Idempotent.
# Runs:
#   1. Worker zone labels (data/edge/control)
#   2. PriorityClass on critical components
#   3. Kyverno HA scale + PDB
#   4. LimitRange in all user namespaces
#   5. kubelet-watchdog DaemonSet
set -e
ROOT="$(dirname "$(readlink -f "$0")")/.."
echo "=== 1. Zone labels ==="
bash "$ROOT/infra/zone-labels.sh"
echo "=== 2. Priority on critical ==="
bash "$ROOT/infra/set-priority.sh"
echo "=== 3. Kyverno HA ==="
kubectl -n kyverno scale deploy kyverno-admission-controller --replicas=2
kubectl apply -f "$ROOT/manifests/kyverno-pdb.yaml"
echo "=== 4. LimitRange in user namespaces ==="
bash "$ROOT/infra/apply-limitrange.sh"
echo "=== 5. kubelet-watchdog ==="
kubectl apply -f "$ROOT/manifests/kubelet-watchdog.yaml"
echo "=== Done. Verify with: ==="
echo "  kubectl get nodes -L workload-zone"
echo "  kubectl -n kyverno get pdb,deploy"
echo "  kubectl get limitrange -A"
echo "  kubectl -n node-problem-detector get ds"
