#!/bin/bash
# ============================================================================
# 04-helm-charts.sh  — Install all Helm releases captured in this repo.
# ----------------------------------------------------------------------------
# Reads install/helm-charts.csv (namespace,name,chart,version,repo,values_file).
# Skips releases already installed in same namespace with same name.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CSV="${REPO_ROOT}/install/helm-charts.csv"

[ -f "$CSV" ] || { echo "Missing $CSV"; exit 1; }

# Add repos first (deduplicated)
echo "[04] Adding helm repos..."
awk -F',' 'NR>1 && $5 ~ /^https/ {print $5}' "$CSV" | sort -u | while read -r url; do
  name="$(basename "$url" | sed 's|\.[a-z]*$||')"
  helm repo add "$name" "$url" >/dev/null 2>&1 || true
done
helm repo update >/dev/null

# Install / upgrade each chart
echo "[04] Installing releases..."
tail -n +2 "$CSV" | while IFS=',' read -r ns name chart version repo values_file; do
  [ -z "$name" ] && continue
  vals_arg=""
  if [ -n "$values_file" ] && [ -f "${REPO_ROOT}/${values_file}" ]; then
    vals_arg="-f ${REPO_ROOT}/${values_file}"
  fi
  echo "  -> ${ns}/${name}  (chart=${chart} version=${version})"
  kubectl create ns "$ns" --dry-run=client -o yaml | kubectl apply -f -
  helm upgrade --install "$name" "$chart" \
    --namespace "$ns" \
    --version "$version" \
    --repo "$repo" \
    $vals_arg \
    --wait --timeout 10m || echo "    [WARN] release ${ns}/${name} failed; continuing"
done

echo "[04] Done."
helm list -A
