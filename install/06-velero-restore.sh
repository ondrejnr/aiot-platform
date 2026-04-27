#!/bin/bash
# ============================================================================
# 06-velero-restore.sh  — Install Velero + restore from Cloudflare R2 backup.
# ----------------------------------------------------------------------------
# Required env vars:
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY  — R2 credentials
#   R2_ENDPOINT                              — https://<acct>.r2.cloudflarestorage.com
#   R2_BUCKET                                — aiot-velero
#   BACKUP_NAME                              — e.g. daily-cluster-backup-20260427030000
# ============================================================================
set -euo pipefail

: "${AWS_ACCESS_KEY_ID:?Set AWS_ACCESS_KEY_ID for R2}"
: "${AWS_SECRET_ACCESS_KEY:?Set AWS_SECRET_ACCESS_KEY for R2}"
: "${R2_ENDPOINT:?Set R2_ENDPOINT (https://<acct>.r2.cloudflarestorage.com)}"
: "${R2_BUCKET:=aiot-velero}"
: "${BACKUP_NAME:?Set BACKUP_NAME (run: velero backup get)}"

VELERO_VERSION="${VELERO_VERSION:-v1.15.0}"

if ! command -v velero >/dev/null 2>&1; then
  curl -fsSL "https://github.com/vmware-tanzu/velero/releases/download/${VELERO_VERSION}/velero-${VELERO_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /tmp
  install -m 0755 "/tmp/velero-${VELERO_VERSION}-linux-amd64/velero" /usr/local/bin/velero
fi

cat >/tmp/r2-creds <<EOF
[default]
aws_access_key_id=${AWS_ACCESS_KEY_ID}
aws_secret_access_key=${AWS_SECRET_ACCESS_KEY}
EOF

velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.11.0 \
  --bucket "${R2_BUCKET}" \
  --secret-file /tmp/r2-creds \
  --backup-location-config "region=auto,s3ForcePathStyle=true,s3Url=${R2_ENDPOINT}" \
  --use-volume-snapshots=false \
  --use-node-agent

rm -f /tmp/r2-creds

echo "[06] Velero installing... waiting"
kubectl -n velero rollout status deploy/velero
sleep 15
velero backup-location get
velero backup get | head

echo "[06] Restoring backup: ${BACKUP_NAME}"
velero restore create "restore-$(date +%s)" --from-backup "${BACKUP_NAME}" --wait
