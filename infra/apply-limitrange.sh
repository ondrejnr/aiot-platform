#!/bin/bash
# Apply default LimitRange to user-workload namespaces.
# Excludes system / operator-managed namespaces that have their own controllers.
set -e

EXCLUDE_REGEX='^(kube-system|kube-public|kube-node-lease|cilium|piraeus-datastore|local-path-storage|cnpg-system|cattle-.*|fleet-.*|cluster-fleet-.*|p-.*|local|tigera-.*|monitoring|cert-manager|ingress-nginx|kyverno|robusta|opentelemetry-operator-system|signoz|tekton-.*|openshift-pipelines|pipelines-as-code|enterprise-contract-service|integration-service|build-service|namespace-lister|release-service|konflux-.*|default-tenant|user-.*|knative-serving|istio-system)$'

kubectl get ns -o name | sed 's|namespace/||' | while read ns; do
  if echo "$ns" | grep -qE "$EXCLUDE_REGEX"; then continue; fi

  cat <<YAML | kubectl apply -f - >/dev/null 2>&1
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: $ns
spec:
  limits:
  - type: Container
    default:
      cpu: 500m
      memory: 512Mi
    defaultRequest:
      cpu: 50m
      memory: 64Mi
    max:
      memory: 4Gi
      cpu: "4"
YAML
  echo "  $ns LimitRange applied"
done
echo "=== Total ==="
kubectl get limitrange -A --no-headers | wc -l
