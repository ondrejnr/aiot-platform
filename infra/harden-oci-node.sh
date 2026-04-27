#!/bin/bash
# Per-node hardening for OCI 11GB nodes (oci-e5-node1, oci-e5-node2).
# Idempotent. Run from aiot-master:
#   sudo bash infra/harden-oci-node.sh 172.16.200.10 /root/.ssh/oci-key1.pem opc
#   sudo bash infra/harden-oci-node.sh 172.16.200.11 /root/.ssh/oci-key2.pem opc
#
# Adds:
#  - 4 GB swapfile (vm.swappiness=10)
#  - kubelet failSwapOn=false + memorySwap=LimitedSwap
#  - tighter eviction thresholds (memory.available 300Mi hard / 800Mi soft)
#  - systemReserved + kubeReserved 300m CPU / 600 Mi mem / 2Gi ephemeral
#  - persistent journald (500 Mi cap, 14 d retention)
#
# Why: 11 GB no-swap nodes went to NotReady whenever kubelet/PLEG
# stalled under sudden memory pressure (Prometheus scrape buffers,
# Karpor ES, mass pod evictions). Swap + tighter eviction prevent
# the runtime hang.
set -e
NODE=$1
KEY=$2
USER=${3:-opc}
[ -z "$NODE" ] || [ -z "$KEY" ] && { echo "Usage: $0 <node-ip> <ssh-key> [user]"; exit 1; }

ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 -i "$KEY" "$USER@$NODE" 'bash -se' <<'REMOTE'
set -e
echo "Host: $(hostname), uptime: $(uptime)"

# 1. Swap (4 GB)
if [ ! -f /swapfile ]; then
  echo "Creating 4GB swapfile..."
  sudo fallocate -l 4G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=4096
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
sudo sysctl -w vm.swappiness=10 vm.min_free_kbytes=131072 >/dev/null
grep -q '^vm.swappiness' /etc/sysctl.d/99-aiot-swap.conf 2>/dev/null || \
  echo -e 'vm.swappiness=10\nvm.min_free_kbytes=131072' | sudo tee /etc/sysctl.d/99-aiot-swap.conf >/dev/null
free -m | grep -E '^Mem|^Swap'

KCFG=/var/lib/kubelet/config.yaml

# 2. Kubelet swap support
if ! grep -q 'failSwapOn' "$KCFG"; then
  sudo tee -a "$KCFG" <<EOF

# Added by AIOT hardening (infra/harden-oci-node.sh)
failSwapOn: false
memorySwap:
  swapBehavior: LimitedSwap
EOF
fi

# 3. Tighter eviction (only if not already configured)
if ! grep -q '^evictionHard:' "$KCFG"; then
  sudo tee -a "$KCFG" <<EOF
evictionHard:
  memory.available: "300Mi"
  nodefs.available: "10%"
  imagefs.available: "10%"
  pid.available: "5%"
evictionSoft:
  memory.available: "800Mi"
  nodefs.available: "15%"
  imagefs.available: "15%"
evictionSoftGracePeriod:
  memory.available: "1m30s"
  nodefs.available: "1m30s"
  imagefs.available: "1m30s"
evictionMaxPodGracePeriod: 60
systemReserved:
  cpu: "300m"
  memory: "600Mi"
  ephemeral-storage: "2Gi"
kubeReserved:
  cpu: "300m"
  memory: "600Mi"
  ephemeral-storage: "2Gi"
EOF
fi

# 4. Persistent journald
if [ ! -d /var/log/journal ]; then
  sudo mkdir -p /var/log/journal
  sudo systemd-tmpfiles --create --prefix /var/log/journal || true
fi
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/aiot.conf >/dev/null <<EOF
[Journal]
Storage=persistent
SystemMaxUse=500M
MaxRetentionSec=14day
EOF
sudo systemctl restart systemd-journald

# 5. Restart kubelet to pick up changes
sudo systemctl daemon-reload || true
sudo systemctl restart kubelet
sleep 5
sudo systemctl is-active kubelet
echo "DONE on $(hostname)"
REMOTE
