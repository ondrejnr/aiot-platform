#!/bin/bash
# Mark critical components with system-cluster-critical priority so they
# are scheduled first and preempt user workloads under pressure.
set -e

# system-cluster-critical (value 2000000000) is built-in. Just patch the deployments.
declare -a TARGETS=(
  "kyverno/Deployment/kyverno-admission-controller"
  "monitoring/Prometheus/prometheus-kube-prometheus-prometheus"
  "monitoring/Alertmanager/prometheus-kube-prometheus-alertmanager"
  "ingress-nginx/DaemonSet/ingress-nginx-controller"
  "kube-system/Deployment/metrics-server"
  "default/DaemonSet/ingress-nginx-controller"
)

for entry in "${TARGETS[@]}"; do
  IFS=/ read ns kind name <<< "$entry"
  if ! kubectl -n "$ns" get "$kind" "$name" >/dev/null 2>&1; then
    echo "  SKIP $ns/$kind/$name (not found)"; continue
  fi

  if [ "$kind" = "Prometheus" ] || [ "$kind" = "Alertmanager" ]; then
    # CR resolver path
    kubectl -n "$ns" patch "$kind" "$name" --type=merge -p '{"spec":{"priorityClassName":"system-cluster-critical"}}' && \
      echo "  patched $ns/$kind/$name"
  else
    kubectl -n "$ns" patch "$kind" "$name" --type=merge -p '{"spec":{"template":{"spec":{"priorityClassName":"system-cluster-critical"}}}}' && \
      echo "  patched $ns/$kind/$name"
  fi
done

echo "=== Verify ==="
kubectl -n kyverno get deploy kyverno-admission-controller -o jsonpath='{.spec.template.spec.priorityClassName}'; echo
kubectl -n monitoring get prometheus prometheus-kube-prometheus-prometheus -o jsonpath='{.spec.priorityClassName}'; echo
kubectl -n monitoring get alertmanager prometheus-kube-prometheus-alertmanager -o jsonpath='{.spec.priorityClassName}'; echo
kubectl -n default get ds ingress-nginx-controller -o jsonpath='{.spec.template.spec.priorityClassName}' 2>/dev/null; echo
kubectl -n kube-system get deploy metrics-server -o jsonpath='{.spec.template.spec.priorityClassName}' 2>/dev/null; echo
