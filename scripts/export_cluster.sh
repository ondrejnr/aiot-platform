#!/usr/bin/env bash
set -euo pipefail
ts="$(date +%F_%H-%M-%S)"
raw="snapshots/raw/full-cluster-${ts}.yaml"
: > "$raw"
while read -r kind; do
  [ -n "$kind" ] || continue
  echo "# SOURCE: $kind" >> "$raw"
  kubectl get "$kind" -A -o yaml >> "$raw" 2>/dev/null || true
  echo -e "\n---" >> "$raw"
done < scripts/resource_kinds.txt
echo "Wrote $raw"
