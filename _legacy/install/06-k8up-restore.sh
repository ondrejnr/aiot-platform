#!/bin/bash
# ============================================================================
# 06-k8up-restore.sh  — Restore PVC data from R2 via k8up.
# ----------------------------------------------------------------------------
# Prerequisites:
#   1. k8up operator already installed (install/04-helm-charts.sh)
#   2. R2 credentials Secret "r2-creds" + restic password Secret "k8up-repo"
#      already present in the target namespace (apply manifests from this repo
#      OR run install/06b-create-k8up-secrets.sh).
#
# Usage examples:
#   # List snapshots in the restic repo for a namespace
#   ./install/06-k8up-restore.sh list aiot
#
#   # Restore a specific PVC from latest snapshot
#   ./install/06-k8up-restore.sh restore aiot data-pg-ha-2 latest
#
# Required env (or .envrc):
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, R2_ENDPOINT, R2_BUCKET (=aiot-velero)
# ============================================================================
set -euo pipefail

CMD="${1:-}"
NS="${2:-}"
PVC="${3:-}"
SNAPSHOT="${4:-latest}"

usage() {
  echo "Usage: $0 list <namespace>"
  echo "       $0 restore <namespace> <pvc-name> [<snapshot-id>|latest]"
  exit 1
}

[ -z "$CMD" ] || [ -z "$NS" ] && usage

case "$CMD" in
  list)
    echo "[06] Snapshots for namespace '${NS}':"
    kubectl -n "$NS" get snapshots.k8up.io -o wide || \
      kubectl -n "$NS" get archives.k8up.io
    ;;
  restore)
    [ -z "$PVC" ] && usage
    NAME="restore-${PVC}-$(date +%s)"
    echo "[06] Creating Restore.k8up.io '${NAME}' in ns ${NS} for PVC ${PVC}"
    cat <<EOF | kubectl apply -f -
apiVersion: k8up.io/v1
kind: Restore
metadata:
  name: ${NAME}
  namespace: ${NS}
spec:
  snapshot: "${SNAPSHOT}"
  restoreMethod:
    folder:
      claimName: ${PVC}
  backend:
    repoPasswordSecretRef:
      name: k8up-repo
      key: password
    s3:
      endpoint: "\${R2_ENDPOINT:-https://ca6c7e99d62811119041b9334c646aaf.r2.cloudflarestorage.com}"
      bucket: "\${R2_BUCKET:-aiot-velero}"
      accessKeyIDSecretRef:
        name: r2-creds
        key: access_key
      secretAccessKeySecretRef:
        name: r2-creds
        key: secret_key
EOF
    echo "[06] Restore submitted; track with:"
    echo "     kubectl -n ${NS} get restore ${NAME} -w"
    ;;
  *)
    usage
    ;;
esac
