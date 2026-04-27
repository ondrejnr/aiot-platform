#!/bin/bash
# ============================================================================
# 05-apply-cluster.sh  — Apply CRDs + cluster-scoped + namespaced manifests.
# ----------------------------------------------------------------------------
# Order:
#   1. CRDs (manifests/_crds/*)
#   2. Namespaces (manifests/_cluster/namespaces.yaml)
#   3. Cluster-scoped (clusterrolebindings, ingressclasses, ...)
#   4. Per-namespace manifests (manifests/<ns>/*)
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
M="${REPO_ROOT}/manifests"

[ -d "$M" ] || { echo "Missing manifests/ — run cron snapshot first or check repo"; exit 1; }

echo "[05] CRDs..."
if [ -d "${M}/_crds" ]; then
  for f in "${M}/_crds"/*.yaml; do
    kubectl apply --server-side --force-conflicts -f "$f" || true
  done
fi

echo "[05] Namespaces + cluster-scoped..."
[ -f "${M}/_cluster/namespaces.yaml" ] && kubectl apply -f "${M}/_cluster/namespaces.yaml" || true
for f in clusterroles clusterrolebindings ingressclasses storageclasses persistentvolumes; do
  [ -f "${M}/_cluster/${f}.yaml" ] && kubectl apply -f "${M}/_cluster/${f}.yaml" || true
done

echo "[05] Per-namespace manifests..."
for nsdir in "${M}"/*/; do
  ns="$(basename "$nsdir")"
  [[ "$ns" == _* ]] && continue
  echo "  -> $ns"
  # Apply in dependency order: configmaps/secrets first, then RBAC, then workloads
  for kind in configmaps roles rolebindings serviceaccounts pvc persistentvolumeclaims \
              services ingresses deployments statefulsets daemonsets jobs cronjobs \
              poddisruptionbudgets; do
    f="${nsdir}${kind}.yaml"
    [ -f "$f" ] && kubectl -n "$ns" apply -f "$f" || true
  done
done

echo "[05] Done. NOTE: Secrets are NOT applied (sanitized in repo)."
echo "     Restore secrets via:  velero restore create --from-backup <name>"
