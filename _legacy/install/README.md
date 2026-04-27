# Installation guide — fresh-cluster bootstrap

This directory contains everything required to recreate the **aiot-platform**
cluster on **brand-new VMs**, in the correct order, from this Git repo.

## Target topology

| Role           | Count | OS                 | Notes                                |
|----------------|------:|--------------------|--------------------------------------|
| Master         |     1 | RHEL/Rocky 9.x     | runs etcd, kube-apiserver, HAProxy   |
| GCP workers    |     2 | RHEL/Rocky 9.x     | `aiot-worker-01`, `aiot-worker-02`   |
| OCI workers    |     2 | Oracle Linux 9.x   | `oci-e5-node1`, `oci-e5-node2` (WG)  |

Pod CIDR: `10.245.0.0/16` · Service CIDR: `10.96.0.0/12` · CNI: **Cilium 1.16.6**
(kubeProxyReplacement, vxlan port 8473, Hubble enabled).

## Prerequisites

- Public IP on master (`35.241.255.137` in production)
- DNS wildcard `*.<master-ip>.nip.io` resolves to master IP (HAProxy SNI)
- For OCI workers: WireGuard tunnel to master (configure separately — see
  [`infra/`](../infra/) snapshot for sample IPs)

## Step-by-step

| # | Script                  | Run on        | Purpose                                              |
|---|-------------------------|---------------|------------------------------------------------------|
| 0 | `00-vm-prereqs.sh`      | every node    | containerd + kubeadm + kubelet + kubectl + helm      |
| 1 | `01-init-master.sh`     | master only   | `kubeadm init` from `infra/kubeadm-config.yaml`      |
|   | (kubeadm join cmd)      | every worker  | join control plane                                   |
| 2 | `02-cilium.sh`          | master        | Cilium CNI (replaces kube-proxy)                     |
| 3 | `03-platform.sh`        | master        | cert-manager + ingress-nginx + local-path SC         |
| 4 | `04-helm-charts.sh`     | master        | all 14 helm releases (Rancher, ArgoCD, Jenkins, ...) |
| 5 | `05-apply-cluster.sh`   | master        | apply CRDs + cluster-scoped + per-NS manifests       |
| 6 | `06-k8up-restore.sh`     | master        | restore PVC data from R2 via k8up Restore CR (optional) 

```bash
# === On EVERY node ===
sudo bash install/00-vm-prereqs.sh

# === On master only ===
sudo bash install/01-init-master.sh
# copy printed `kubeadm join ...` command and run on each worker

# === On master, after all workers joined ===
sudo bash install/02-cilium.sh
sudo bash install/03-platform.sh
sudo bash install/04-helm-charts.sh
sudo bash install/05-apply-cluster.sh

