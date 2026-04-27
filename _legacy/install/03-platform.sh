#!/bin/bash
# ============================================================================
# 03-platform.sh  — Install platform layer:
#   cert-manager, ingress-nginx, local-path-provisioner, ClusterIssuers.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

CERT_MANAGER_VERSION="${CERT_MANAGER_VERSION:-v1.16.2}"
INGRESS_NGINX_VERSION="${INGRESS_NGINX_VERSION:-4.11.3}"
LOCAL_PATH_VERSION="${LOCAL_PATH_VERSION:-v0.0.30}"

# ---------- cert-manager ----------
echo "[03] cert-manager ${CERT_MANAGER_VERSION}"
helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
helm repo update jetstack >/dev/null
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version "${CERT_MANAGER_VERSION}" \
  --set crds.enabled=true
kubectl -n cert-manager rollout status deploy/cert-manager
kubectl -n cert-manager rollout status deploy/cert-manager-webhook

# ClusterIssuers from snapshot
[ -f "${REPO_ROOT}/cluster-wide/clusterissuers.yaml" ] && \
  kubectl apply -f "${REPO_ROOT}/cluster-wide/clusterissuers.yaml" || true

# ---------- ingress-nginx ----------
echo "[03] ingress-nginx ${INGRESS_NGINX_VERSION}"
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
helm repo update ingress-nginx >/dev/null
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --version "${INGRESS_NGINX_VERSION}" \
  --set controller.kind=DaemonSet \
  --set controller.hostNetwork=true \
  --set controller.dnsPolicy=ClusterFirstWithHostNet \
  --set controller.service.type=ClusterIP

# ---------- local-path-provisioner (default StorageClass) ----------
echo "[03] local-path-provisioner ${LOCAL_PATH_VERSION}"
kubectl apply -f "https://raw.githubusercontent.com/rancher/local-path-provisioner/${LOCAL_PATH_VERSION}/deploy/local-path-storage.yaml"
kubectl annotate sc local-path storageclass.kubernetes.io/is-default-class=true --overwrite

# ClusterRoles / ClusterRoleBindings / IngressClasses / PriorityClasses
for f in clusterroles clusterrolebindings ingressclasses priorityclasses; do
  [ -f "${REPO_ROOT}/cluster-wide/${f}.yaml" ] && \
    kubectl apply -f "${REPO_ROOT}/cluster-wide/${f}.yaml" || true
done

echo "[03] Platform layer ready."
kubectl get sc
kubectl get clusterissuers
