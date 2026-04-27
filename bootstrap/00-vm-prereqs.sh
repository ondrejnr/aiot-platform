#!/bin/bash
# bootstrap/00-vm-prereqs.sh — runs on EVERY node (master + workers)
# Installs containerd, kubeadm, kubelet, kubectl, helm. Disables swap,
# sets sysctl, kernel modules. Idempotent.
set -euo pipefail

K8S_MINOR="${K8S_MINOR:-v1.32}"
HELM_VERSION="${HELM_VERSION:-v3.16.3}"

. /etc/os-release
echo "[00] OS: $NAME $VERSION (id=$ID)"

# --- kernel modules + sysctl
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

# --- swap off
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab || true

# --- disable firewalld (Cilium handles netpol)
systemctl disable --now firewalld 2>/dev/null || true

# --- SELinux permissive on RHEL family
if [ -f /etc/selinux/config ]; then
  setenforce 0 || true
  sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config
fi

# --- packages
case "$ID" in
  rhel|rocky|almalinux|centos|ol)
    cat >/etc/yum.repos.d/kubernetes.repo <<EOF
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/rpm/repodata/repomd.xml.key
exclude=kubelet kubeadm kubectl cri-tools kubernetes-cni
EOF
    dnf install -y --allowerasing containerd kubelet kubeadm kubectl \
      curl jq tar git iproute-tc socat conntrack-tools openssl \
      --disableexcludes=kubernetes
    ;;
  ubuntu|debian)
    apt-get update
    apt-get install -y apt-transport-https ca-certificates curl gnupg jq git \
      iproute2 socat conntrack openssl
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/Release.key \
      | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/ /" \
      >/etc/apt/sources.list.d/kubernetes.list
    apt-get update
    apt-get install -y containerd kubelet kubeadm kubectl
    ;;
  *) echo "Unsupported OS: $ID"; exit 1 ;;
esac

# --- containerd
mkdir -p /etc/containerd
containerd config default >/etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl enable --now containerd
systemctl restart containerd

systemctl enable --now kubelet || true   # will run after kubeadm

# --- helm
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz | tar -xz -C /tmp
  install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm
fi

echo "[00] DONE"
containerd --version
kubeadm version -o short
kubectl version --client | head -1
helm version --short
