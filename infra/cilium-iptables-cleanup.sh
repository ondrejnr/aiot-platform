#!/usr/bin/env bash
# cilium-iptables-cleanup.sh
# Run on demand when cilium-agent leaves stale OLD_CILIUM_* iptables chains
# after an unclean restart (causes 10s reconcile-fail spam in agent logs).
#
# Usage:
#   bash cilium-iptables-cleanup.sh                  # all cilium-agent pods
#   bash cilium-iptables-cleanup.sh <node-name>      # single node
set -euo pipefail

NS=kube-system
SEL=k8s-app=cilium

mapfile -t PODS < <(kubectl -n "$NS" get pod -l "$SEL" \
  -o jsonpath='{range .items[*]}{.metadata.name} {.spec.nodeName}{"\n"}{end}')

TARGET="${1:-}"

for line in "${PODS[@]}"; do
  pod="${line%% *}"; node="${line##* }"
  [ -z "$pod" ] && continue
  [ -n "$TARGET" ] && [ "$node" != "$TARGET" ] && continue

  echo "=== $pod on $node ==="
  for tbl in nat mangle filter raw; do
    chains=$(kubectl -n "$NS" exec "$pod" -c cilium-agent -- \
      iptables -t "$tbl" -L 2>/dev/null | awk '/^Chain OLD_CILIUM_/ {print $2}' || true)
    for c in $chains; do
      echo "  -> $tbl/$c (flush + delete)"
      kubectl -n "$NS" exec "$pod" -c cilium-agent -- iptables -t "$tbl" -F "$c" || true
      kubectl -n "$NS" exec "$pod" -c cilium-agent -- iptables -t "$tbl" -X "$c" || true
    done
  done
done
echo "done"
