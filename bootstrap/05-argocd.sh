#!/bin/bash
# bootstrap/05-argocd.sh — install ArgoCD with KSOPS plugin enabled.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARGOCD_VERSION="${ARGOCD_VERSION:-7.7.10}"

helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update argo >/dev/null

# values.yaml mounts the sops-age secret into argocd-repo-server and registers
# KSOPS as a kustomize plugin
cat >/tmp/argocd-values.yaml <<'EOF'
configs:
  cm:
    kustomize.buildOptions: --enable-alpha-plugins --enable-exec
  params:
    server.insecure: true            # behind ingress-nginx with TLS termination

server:
  ingress:
    enabled: true
    ingressClassName: nginx
    hostname: argocd.aiot.local
    tls: true

repoServer:
  volumes:
    - name: sops-age
      secret:
        secretName: sops-age
    - name: custom-tools
      emptyDir: {}
  volumeMounts:
    - mountPath: /home/argocd/.config/sops/age
      name: sops-age
  initContainers:
    - name: install-ksops
      image: viaductoss/ksops:v4.3.3
      command: [/bin/sh, -c]
      args:
        - |
          echo "Installing KSOPS"
          mv ksops /custom-tools/
          mv kustomize /custom-tools/
      volumeMounts:
        - mountPath: /custom-tools
          name: custom-tools
  env:
    - name: SOPS_AGE_KEY_FILE
      value: /home/argocd/.config/sops/age/keys.txt
  extraVolumeMounts:
    - mountPath: /usr/local/bin/kustomize
      name: custom-tools
      subPath: kustomize
    - mountPath: /usr/local/bin/ksops
      name: custom-tools
      subPath: ksops
EOF

helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --version "$ARGOCD_VERSION" \
  -f /tmp/argocd-values.yaml

echo "[05] Waiting for ArgoCD..."
kubectl -n argocd rollout status deploy/argocd-server
kubectl -n argocd rollout status deploy/argocd-repo-server

echo
echo "[05] Initial admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo

echo "Port-forward to UI:"
echo "  kubectl -n argocd port-forward svc/argocd-server 8080:80"
