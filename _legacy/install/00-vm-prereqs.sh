#!/bin/bash
# ============================================================================
# 00-vm-prereqs.sh  — Prepare a fresh Linux VM (RHEL/Rocky/AlmaLinux 9, Ubuntu 22.04+)
# ----------------------------------------------------------------------------
# Installs: containerd, kubeadm, kubelet, kubectl, helm, common tools.
# Run AS ROOT on every node (master + workers) BEFORE 01-init-master.sh.
# ============================================================================
set -euo pipefail

K8S_VERSION="${K8S_VERSION:-v1.32}"
HELM_VERSION="${HELM_VERSION:-v3.16.3}"

echo "[00] Detect OS..."
. /etc/os-release
echo "    -> $NAME $VERSION"

# ----- Kernel modules + sysctl -----
modprobe br_netfilter overlay
cat >/etc/modules-load.d/k8s.conf <<EOF
overlay
br_netfilter
EOF
cat >/etc/sysctl.d/99-k8s.conf <<EOF
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system >/dev/null

# ----- Disable swap -----
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

# ----- Disable firewalld (we use Cilium NetworkPolicy + iptables flushed) -----
systemctl disable --now firewalld 2>/dev/null || true

# ----- Disable SELinux (or set permissive) on RHEL family -----
if [ -f /etc/selinux/config ]; then
  setenforce 0 || true
  sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config
fi

# ----- Install containerd + k8s tools -----
case "$ID" in
  rhel|rocky|almalinux|centos|ol)
    cat >/etc/yum.repos.d/kubernetes.repo <<EOF
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/${K8S_VERSION}/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/${K8S_VERSION}/rpm/repodata/repomd.xml.key
exclude=kubelet kubeadm kubectl cri-tools kubernetes-cni
EOF
    dnf install -y containerd.io kubelet kubeadm kubectl --disableexcludes=kubernetes \
      || dnf install -y https://download.docker.com/linux/centos/9/x86_64/stable/Packages/containerd.io-1.7.22-3.1.el9.x86_64.rpm
    dnf install -y kubelet kubeadm kubectl --disableexcludes=kubernetes
    dnf install -y curl jq tar git iproute-tc socat conntrack-tools
    ;;
  ubuntu|debian)
    apt-get update
    apt-get install -y apt-transport-https ca-certificates curl gnupg jq git iproute2 socat conntrack
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/${K8S_VERSION}/deb/Release.key \
      | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_VERSION}/deb/ /" \
      >/etc/apt/sources.list.d/kubernetes.list
    apt-get update
    apt-get install -y containerd kubelet kubeadm kubectl
    ;;
  *)
    echo "Unsupported OS: $ID"; exit 1 ;;
esac

systemctl enable --now containerd
systemctl enable --now kubelet || true   # kubelet will fail until kubeadm init

# ----- containerd config: SystemdCgroup=true, sandbox image -----
mkdir -p /etc/containerd
containerd config default >/etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd

# ----- helm -----
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz | tar -xz -C /tmp
  install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm
fi

echo "[00] DONE — versions:"
containerd --version
kubeadm version -o short
kubectl version --client -o yaml | head -5
helm version --short
