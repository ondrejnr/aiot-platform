# aiot-platform — cluster snapshot

Snapshot of the running **aiot2** Kubernetes cluster as of the export date. Purpose: serve as a source-of-truth reference to rebuild the cluster on new infrastructure if the current GCP project gets suspended.

> This repository contains **manifests and configs only**. Data (databases, object stores, PVC contents) are **not** included — those live in the separate Velero R2 backup (`s3://aiot-velero`).

## Topology

| Node | Role | IP (internal) | IP (external) | OS | Location |
|---|---|---|---|---|---|
| aiot-master | control-plane | 10.132.0.2 | 35.241.255.137 | CentOS Stream 9 | GCP `europe-west1-b` |
| aiot-worker-01 | worker | 10.132.0.3 | — | CentOS Stream 9 | GCP `europe-west1-b` |
| aiot-worker-02 | worker | 10.132.0.4 | — | CentOS Stream 9 | GCP `europe-west1-b` |
| oci-e5-node1 | worker | 172.16.200.10 (WG) | — | Oracle Linux 9.7 | OCI `eu-frankfurt-1` |
| oci-e5-node2 | worker | 172.16.200.11 (WG) | — | Oracle Linux 9.7 | OCI `eu-frankfurt-1` |
| oci-test-node1 | worker (ml-training) | 172.16.200.12 (WG) | — | Oracle Linux 9.7 | OCI `eu-frankfurt-1` |

- **Kubernetes version**: v1.32.13 (kubeadm)
- **CNI**: flannel (vxlan, pod CIDR 10.244.0.0/16)
- **OCI nodes** connect via WireGuard tunnel to the GCP master
- **Public entrypoint**: 35.241.255.137 → HAProxy on master → workers' nginx-ingress (80/443) or SSH fallback (127.0.0.1:2222)
- **GCP project**: `upbeat-sunup-493110-n3` (zone europe-west1-b)
- **OCI tenancy**: separate (independent of GCP — survives GCP suspension)

## DNS / Public services

All services use `*.35.241.255.137.nip.io` hostnames with Let's Encrypt (cert-manager HTTP-01). See `namespaces/*/ingresses.yaml` for full list.

Major endpoints:
- Kubeflow: `kubeflow.35.241.255.137.nip.io`
- Jenkins: `jenkins.35.241.255.137.nip.io`
- Gitea: `gitea.35.241.255.137.nip.io`
- MLflow: `mlflow.35.241.255.137.nip.io`
- SigNoz: `signoz.35.241.255.137.nip.io`
- Mattermost: `mm.35.241.255.137.nip.io`
- Puppet Enterprise: `pe.35.241.255.137.nip.io`
- Chef Automate: `chef.35.241.255.137.nip.io`
- Grafana: `grafana.35.241.255.137.nip.io`

## Repository layout

```
aiot-platform/
├── README.md                       # this file
├── cluster/
│   └── versions.md                 # k8s/kubectl versions, node list
├── cluster-wide/
│   ├── clusterroles.yaml
│   ├── clusterrolebindings.yaml
│   ├── clusterissuers.yaml         # cert-manager
│   ├── storageclasses.yaml
│   ├── ingressclasses.yaml
│   ├── priorityclasses.yaml
│   ├── persistentvolumes.yaml
│   ├── nodes.yaml                  # labels/taints only
│   ├── crds.txt                    # CRD names/groups
│   ├── images.txt                  # all images used
│   └── helm-releases.yaml
├── namespaces/
│   └── <ns>/
│       ├── deployments.yaml
│       ├── statefulsets.yaml
│       ├── daemonsets.yaml
│       ├── cronjobs.yaml
│       ├── services.yaml
│       ├── ingresses.yaml
│       ├── configmaps.yaml
│       ├── pvcs.yaml
│       ├── secrets.sanitized.yaml  # NO values, only key names
│       ├── serviceaccounts.yaml
│       ├── rbac.yaml               # roles + rolebindings
│       ├── istio-*.yaml            # VS/Gateway/AuthzPolicy/EnvoyFilter/Telemetry
│       └── cr-*.yaml               # Kubeflow/KServe/Argo CRs
├── infra/
│   ├── haproxy/haproxy.cfg         # master HAProxy (SNI + HTTP-01)
│   ├── kubeadm-config.yaml
│   ├── kube-apiserver.yaml         # static pod manifest
│   ├── etcd.yaml
│   ├── kubelet-config.yaml
│   ├── cni-flannel.conflist
│   ├── gcp-firewall-rules.yaml
│   └── gcp-instances.yaml
└── inventory/
    └── semaphore-configmaps.yaml
```

## What is **NOT** in this repo

- **Secret values** — `secrets.sanitized.yaml` keeps only metadata + list of keys. You must recreate secrets (passwords, tokens, TLS certs) from password manager / regenerate.
- **PVC data** — database contents, MLflow artifacts, Jenkins workspace etc. Those live in:
  - Velero R2 backup: `s3://aiot-velero/velero/backups/` (since 2026-04-17, with `defaultVolumesToFsBackup=true` → Kopia filesystem backup)
  - pg-ha `pg_dumpall` → optional manual dump
- **etcd snapshot** — single file, ~100 MiB, store separately (not in git)
- **Container images built in-house** — in cluster registry `10.132.0.2:30500`. For rebuild, push them to a registry surviving the migration (GitHub Container Registry / Docker Hub / Cloudflare R2 via Harbor).
- **Chef Automate state + Puppet Enterprise DB** — these are on aiot-worker-01 filesystem (`/hab`, `/opt/puppetlabs`). Needs separate tar dump.

## Rebuild recipe

On fresh infrastructure:

1. **Provision VMs** with same specs (e2-standard-4 or equivalent, 50+50 GB disks)
2. **Install** containerd + kubeadm + kubelet v1.32.13, flannel CNI
3. **`kubeadm init`** on master, `kubeadm join` on workers (see `infra/kubeadm-config.yaml`)
4. **Restore public endpoint**:
   - Either keep the same public IP (if portable across cloud providers)
   - Or update DNS: replace `35.241.255.137` with new IP in all `*.nip.io` ingresses
   - Copy HAProxy config from `infra/haproxy/haproxy.cfg`
5. **Apply cluster-wide resources**:
   ```bash
   kubectl apply -f cluster-wide/storageclasses.yaml
   kubectl apply -f cluster-wide/ingressclasses.yaml
   # Install: cert-manager (Helm), nginx-ingress (DaemonSet), velero (Helm)
   kubectl apply -f cluster-wide/clusterissuers.yaml
   ```
6. **Recreate namespaces and secrets manually** (from password manager)
7. **Apply namespace manifests**:
   ```bash
   for ns in namespaces/*/; do
     kubectl apply -f "$ns" --recursive --prune=false
   done
   ```
8. **Restore data**:
   ```bash
   velero restore create --from-backup daily-cluster-backup-<latest>
   ```
9. **OCI nodes**: re-setup WireGuard tunnel, rejoin cluster with new control-plane endpoint
10. **Re-issue Let's Encrypt certs** (cert-manager will do it automatically)

## Credentials strategy (for rebuild)

| Component | Stored where | Action on rebuild |
|---|---|---|
| PostgreSQL (pg-ha) | password manager | recreate as K8s Secret |
| Gitea admin | password manager | recreate via `gitea admin user create` |
| Jenkins admin | password manager | bootstrap via JCasC |
| Mattermost | DB-backed | restored via pg_restore |
| Kubeflow Dex users | static in dex ConfigMap | restored via manifest |
| Cloudflare R2 (Velero) | password manager | Secret `velero/cloud-credentials` |
| Let's Encrypt | — | auto-reissued |
| OCI SSH keys | `aiot-master:/root/.ssh/*.pem` | re-deploy from backup |

## Known gotchas

- **HAProxy restart kills SSH sessions on port 443** — use GCP IAP tunnel when reloading
- **GCP default network security** sets `ip_forward=0`; need `/etc/sysctl.d/99-k8s-forward.conf` with `net.ipv4.ip_forward=1`
- **OCI nodes `inotify`** limit too low for Kubeflow profiles-controller — set `fs.inotify.max_user_instances=1024`
- **OCI nodes DNS search domains** (`vcn*.oraclevcn.com`) break cluster.local resolution — use kubelet config with explicit resolvConf `/etc/kubelet-resolv.conf`
- **`defaultVolumesToFsBackup=true`** in Velero schedule was enabled 2026-04-19; first full backup next 03:00 UTC
- **`local-path` StorageClass** (default) pins data to node — no replication, no HA. Losing a worker loses its PVs.

## Related external state

| Resource | Location | Contains |
|---|---|---|
| Velero backups | Cloudflare R2 `aiot-velero` bucket | K8s manifests + Kopia filesystem snapshots |
| GitHub (this) | `ondrejnr/aiot-platform` | this snapshot |
| Gitea (internal) | `https://gitea.35.241.255.137.nip.io` | app repos (`aiot-pipeline-demo`, `aiot-infra`) |
| OCI Always Free tier | OCI tenancy (independent) | 3 worker VMs + 200 GB block volumes |

## Export metadata

- Generated by: `tmp/export_cluster.sh` on aiot-master
- Secrets sanitized: `data`/`stringData` removed, only metadata + key names preserved
- Noise stripped: `resourceVersion`, `uid`, `creationTimestamp`, `managedFields`, `status` removed from all manifests
- `kubectl.kubernetes.io/last-applied-configuration` annotation removed
