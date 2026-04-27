#!/bin/bash
# bootstrap/04-sops-age.sh — install sops + age + KSOPS plugin for ArgoCD.
# Required env: AGE_KEY_FILE — path to the age PRIVATE key (will be loaded into argocd-repo-server).
# Public key (age1...) is committed in secrets/.sops.yaml; private key never committed.
set -euo pipefail

: "${AGE_KEY_FILE:?Set AGE_KEY_FILE=/path/to/age.key (private)}"
[ -f "$AGE_KEY_FILE" ] || { echo "AGE key not found: $AGE_KEY_FILE"; exit 1; }

# Install sops + age binaries (used by ksops + by maintainers locally)
SOPS_VERSION="${SOPS_VERSION:-v3.9.4}"
AGE_VERSION="${AGE_VERSION:-v1.2.1}"

if ! command -v sops >/dev/null 2>&1; then
  curl -fsSL "https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}.linux.amd64" \
    -o /usr/local/bin/sops
  chmod +x /usr/local/bin/sops
fi
if ! command -v age >/dev/null 2>&1; then
  curl -fsSL "https://github.com/FiloSottile/age/releases/download/${AGE_VERSION}/age-${AGE_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /tmp
  install -m 0755 /tmp/age/age /usr/local/bin/age
  install -m 0755 /tmp/age/age-keygen /usr/local/bin/age-keygen
fi

# Create namespace + secret with age private key (consumed by argocd-repo-server)
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl -n argocd create secret generic sops-age \
  --from-file=keys.txt="$AGE_KEY_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[04] sops/age installed. age secret created in argocd/sops-age."
