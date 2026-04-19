# aiot-platform

> **AIoT cluster snapshot** — live manifests and configuration of an end-to-end platform for **industrial IoT data ingestion, AI/ML processing, and observability**. Exported from the running cluster as a source of truth for disaster recovery, audits, and documentation.

---

## Purpose

This repository is a **versioned, sanitized export** of the Kubernetes cluster that powers the AIoT platform.  
It captures **everything** needed to rebuild the control plane and workloads on new infrastructure — manifests, CRDs, Helm releases, ingress topology, configuration management playbooks and cookbooks, backup definitions — while secrets and dynamic data are intentionally excluded (see [What is *not* here](#what-is-not-here)).

The platform itself is designed around three pillars:

1. **Edge → Cloud data pipeline** — MQTT ingestion, stream processing, time-series storage, digital twin
2. **AI / ML stack** — model training (Kubeflow), experiment tracking (MLflow), inference serving (KServe), RAG (Qdrant + Open-WebUI + LLM)
3. **Configuration & lifecycle management** — Chef Automate, Puppet Enterprise, Ansible/Semaphore, Jenkins CI, Velero DR

---

## Platform at a glance

```
                      ┌───────────────────────────────────────────────┐
                      │           Public entry (35.241.255.137)        │
                      │       HAProxy (SNI → nginx-ingress on workers) │
                      └───────────────────────────────────────────────┘
                                             │
         ┌──────────────────┬─────────────────┴──────────────────┬──────────────────┐
         ▼                  ▼                                    ▼                  ▼
  ┌────────────┐   ┌─────────────────┐            ┌────────────────────────┐  ┌──────────────┐
  │ IoT layer  │   │  AI / ML layer  │            │   Platform services    │  │  Observability│
  │            │   │                 │            │                        │  │              │
  │  EMQX      │──▶│  Kubeflow       │            │  Chef Automate         │  │  SigNoz      │
  │  (MQTT)    │   │  MLflow         │            │  Puppet Enterprise     │  │  Grafana     │
  │  n8n       │   │  KServe         │            │  Jenkins + Gitea       │  │  Prometheus  │
  │  pg-sink   │   │  Qdrant (RAG)   │            │  Semaphore (Ansible)   │  │  VictoriaM.  │
  │  Digital   │   │  Open-WebUI     │            │  Velero (→ Cloudflare R2)│  │  ClickHouse │
  │  Twin      │   │  Inference svc  │            │  Headlamp, Mattermost  │  │              │
  └────────────┘   └─────────────────┘            └────────────────────────┘  └──────────────┘
         │                  │                                    │                  │
         └──────────────────┴────────────────────────────────────┴──────────────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │   CloudNativePG (pg-ha)     │
                              │   shared Postgres cluster   │
                              │   aiot · mlflow · n8n       │
                              │   mattermost · signoz · …   │
                              └─────────────────────────────┘
```

---

## Cluster topology

| Node             | Role           | IP (internal)         | OS                | Location              |
| ---------------- | -------------- | --------------------- | ----------------- | --------------------- |
| aiot-master      | control-plane  | 10.132.0.2            | CentOS Stream 9   | GCP `europe-west1-b`  |
| aiot-worker-01   | worker         | 10.132.0.3            | CentOS Stream 9   | GCP `europe-west1-b`  |
| aiot-worker-02   | worker         | 10.132.0.4            | CentOS Stream 9   | GCP `europe-west1-b`  |
| oci-e5-node1     | worker         | 172.16.200.10 (WG)    | Oracle Linux 9.7  | OCI `eu-frankfurt-1`  |
| oci-e5-node2     | worker         | 172.16.200.11 (WG)    | Oracle Linux 9.7  | OCI `eu-frankfurt-1`  |
| oci-test-node1   | worker (ml)    | 172.16.200.12 (WG)    | Oracle Linux 9.7  | OCI `eu-frankfurt-1`  |

- **Kubernetes**: v1.32.13 (vanilla kubeadm)
- **CNI**: flannel — pod CIDR `10.244.0.0/16`, vxlan overlay
- **Multi-cloud**: OCI nodes join the GCP control plane over a **WireGuard** tunnel; the OCI tenancy is independent of the GCP project and survives GCP outages
- **Public entrypoint**: single IP `35.241.255.137` → **HAProxy** on master → SNI-based TCP proxy to workers' `nginx-ingress` DaemonSet (ports 80/443), with SSH fallback on port 443
- **TLS**: `cert-manager` + Let's Encrypt (HTTP-01), ClusterIssuer `letsencrypt-prod`
- **Storage**: single `local-path` StorageClass (Rancher local-path provisioner) — data is pinned to the node hosting the PVC; **Velero is the only HA/DR path**

---

## The AI data-processing pipeline

The AIoT workflow moves sensor data from the edge all the way to trained, versioned models and an RAG-enabled chat interface.

### 1. Ingestion — `emqx`, `aiot`

- **EMQX** (namespace `emqx`) terminates **MQTT** from field devices (sensor simulators in `aiot/sensor-simulator`)
- **n8n** (namespace `n8n`) orchestrates low-code integration flows (HTTP, webhooks, cron)
- **pg-sink** (in `aiot`) persists raw telemetry into the `aiot` database on `pg-ha`

### 2. Storage — `aiot`, `cnpg-system`

- **CloudNativePG cluster** `pg-ha` (3 replicas in `aiot`) — single source of truth for all tabular/relational data (sensor readings, MLflow metadata, n8n workflows, Mattermost, SigNoz metadata, …)
- Partitioning and cleanup handled by CronJobs: `pg-partition-mgr`, `pg-sensor-cleanup`, `sensor-data-retention`, `postgres-backup`
- Secondary index/feature store: **Qdrant** (namespace `aiot`) for vector embeddings used by RAG

### 3. AI / ML — `kubeflow`, `kubeflow-user-example-com`, `mlflow`, `inference`

- **Kubeflow** (full install: Pipelines v2, Katib, Training Operator, Notebooks, KServe, Central Dashboard, Profiles)
- **Profiles / multi-tenancy**: `kubeflow-user-example-com` namespace hosts the default user, with per-user namespaces (`p-sqf5p`, `p-wpbsz`, `user-5wxc8`) managed by the Profiles controller
- **Training pipeline** `aiot-forward-maintenance-v2` — Argo-based pipeline for predictive maintenance on sensor data, chained with:
  - `aiot-retrain-weekly` CronJob — triggers a new pipeline run every week with fresh data
  - `aiot-register-best` — promotes the best-scoring model run to MLflow Registry
  - `aiot-rollout-model` — updates the served `InferenceService` with the new model URI
- **MLflow** (namespace `mlflow`) — experiment tracking, model registry; backed by `mlflow` DB on `pg-ha`; artifact store currently on Velero-tracked local PVC (migrating to MinIO-on-GCP-disk is planned)
- **KServe** — `maintenance-predictor` `InferenceService` under `kubeflow-user-example-com`, exposed through Knative + Istio on `inference.35.241.255.137.nip.io`
- **Qdrant + rag-worker + Open-WebUI** (in `aiot`) — vector DB + RAG ingestion worker + chat UI, with LLM backends reachable from the cluster

### 4. Delivery — `istio-system`, `knative-serving`, `inference`

- **Istio** ingress gateway for Kubeflow and KServe traffic (`kubeflow.*`, inference endpoints)
- **Knative Serving** provides autoscaled, revision-based model deployments for KServe
- `aiot-inference` (namespace `inference`) — thin connector service that exposes business-level prediction APIs on `inference.35.241.255.137.nip.io`

---

## Configuration management

### Chef Automate — `chef`, `chef-webhook`

- **Chef Automate** runs **outside Kubernetes**, as a systemd service (`chef-automate.service`) on `aiot-worker-01`, exposed on port `8443` and published under `chef.35.241.255.137.nip.io`
- **Chef Infra Server** drives node convergence across all 6 cluster nodes + test VMs
- Namespace **`chef-webhook`** hosts a webhook receiver that bridges Chef Automate events (compliance runs, client converges, InSpec scans) into the cluster — results land on Mattermost (`mm.35.241.255.137.nip.io`, channel `#k8s`) and into Grafana dashboards
- Compliance scans are exported under `inspec-scans` namespace for long-term retention

### Puppet Enterprise — `chef` ns (`pe.*` ingress), host-level

- **Puppet Enterprise 2023.x** runs on `aiot-worker-01` as a full PE stack (systemd units: `pe-nginx`, `pe-puppetserver`, `pe-postgresql`, `pe-puppetdb`, `pe-orchestration-services`, `pe-ace-server`, `pe-bolt-server`, `pe-host-action-collector`, `pe-console-services`)
- Console at `pe.35.241.255.137.nip.io` (admin)
- **All 6 cluster nodes** are managed agents (`noop=true`), plus demo VMs
- **Patch Management** node group (`aae9e4cd-fed5-4f07-8149-98a699a3b692`) with tasks: `agent_health`, `clean_cache`, `last_boot_time`, `patch_server`, `refresh_fact`
- Puppet and Chef run **side by side**: Puppet handles host-level state (packages, kernel params, systemd units, file drops), Chef handles application-layer state and compliance reporting

### Ansible via Semaphore — `semaphore`

- **Semaphore UI** (namespace `semaphore`) wraps Ansible playbooks with scheduling, history, and audit log
- Playbooks cover **operational tasks** (not drift remediation — that's Puppet/Chef):
  - Health check, uptime, disk usage, gather facts, ping
  - WireGuard check, firewall audit, housekeeping
  - OS check (report), OS update apply, reboot planner, certs check
- Inventory synced from the cluster node list

### Jenkins + Gitea — `jenkins`, `gitea`

- **Gitea** — self-hosted Git (namespace `gitea`), the primary source for CI repos (e.g. `aiot-pipeline-demo`)
- **Jenkins** — multibranch + classic pipelines, builds container images, pushes to the internal registry (namespace `registry`, NodePort 30500), and triggers Kubeflow pipeline runs
- Credentials (Gitea PAT, registry, Docker Hub) stored in Jenkins domain credentials

---

## Backup & disaster recovery — `velero`, `vui`, `etcd-backup`

Backup is a **first-class concern** because `local-path` storage has no replication.

### Velero

- **Target**: Cloudflare R2 bucket `s3://aiot-velero` (S3-compatible, endpoint `*.r2.cloudflarestorage.com`)
- **Schedule** `daily-cluster-backup` (namespace `velero`) — every day at 03:00 UTC, retention 7 days
- **Scope**: all cluster + namespaced Kubernetes objects (manifests, CRs, ConfigMaps, Secrets metadata), excluding ephemeral/log-like resources (`events`, `replicasets.apps`, `nodes`) and noisy namespaces (`kube-system`, `kube-flannel`, `local-path-storage`, `monitoring`, `signoz`, `victoriametrics`, `velero`, `knative-serving`, `opentelemetry-operator-system`)
- **File-system backup** (Kopia) per-pod-volume is available per-namespace via `BackupRepository` CRs (`aiot-default-kopia-*`, `kubeflow-default-kopia-*`, `mlflow-default-kopia-*`, `jenkins-default-kopia-*`, etc.) — enabled selectively for stateful workloads whose data must survive a node loss
- **Restore is the exit strategy**: rebuilding a new cluster consists of applying the manifests from this repo, then running `velero restore create --from-backup <latest>` to rehydrate CRs and (optionally) volume data

### vui

- Namespace `vui` hosts the **Velero web UI**, published on `vui.35.241.255.137.nip.io`
- Read-only and admin service accounts (`vui-readonly-sa`, `vui-admin-sa`)

### etcd

- Namespace **`etcd-backup`** runs a `CronJob` that snapshots the kubeadm etcd on a schedule (via `etcdctl` in the etcd pod's container). Snapshots are stored on the master and mirrored to R2.

---

## Public services

All services are published under `*.35.241.255.137.nip.io` with Let's Encrypt certificates.

| Category          | Endpoint (hostname)                            | Namespace         | Notes                                  |
| ----------------- | ---------------------------------------------- | ----------------- | -------------------------------------- |
| Kubeflow          | `kubeflow.*`                                   | `istio-system`    | Multi-tenant, Dex + oauth2-proxy       |
| ML inference      | `inference.*`                                  | `inference`       | KServe-backed                          |
| AI / chat         | `chat.*`                                       | `aiot`            | Open-WebUI                             |
| RAG API           | `rag.*`, `qdrant.*`                            | `aiot`            |                                        |
| IoT core          | `api.*`, `twin.*`, `ngrok.*`                   | `aiot`            | API gateway, Digital Twin              |
| CI / SCM          | `jenkins.*`, `gitea.*`                         | `jenkins`, `gitea`|                                        |
| Config mgmt       | `pe.*`, `chef.*`, `webhook.*`                  | host / `chef-webhook` | Puppet Enterprise, Chef Automate  |
| Automation UI     | `semaphore.*`                                  | `semaphore`       | Ansible via Semaphore                  |
| DB / data         | `pgadmin.*`, `cloudbeaver.*`, `emqx.*`         | `aiot`, `emqx`    |                                        |
| Experiments       | `mlflow.*`                                     | `mlflow`          |                                        |
| Observability     | `grafana.*`, `prometheus.*`, `vm.*`, `signoz.*`| `monitoring`, `victoriametrics`, `signoz` |                         |
| Ops               | `headlamp.*`, `mm.*`, `n8n.*`                  | `headlamp`, `mattermost`, `n8n` |                              |
| DR                | `vui.*`                                        | `vui`             | Velero UI                              |

---

## Repository layout

```
aiot-platform/
├── README.md                ← this file
├── cluster-wide/            ← cluster-scoped resources
│   ├── crds.txt                (CRD names list)
│   ├── clusterroles.yaml
│   ├── clusterrolebindings.yaml
│   ├── clusterissuers.yaml
│   ├── ingressclasses.yaml
│   ├── storageclasses.yaml
│   ├── priorityclasses.yaml
│   ├── persistentvolumes.yaml
│   ├── nodes.yaml
│   ├── helm-releases.yaml      (all Helm releases + chart versions)
│   └── images.txt              (every container image currently used)
├── infra/                   ← host-level / platform files
│   ├── kubeadm-config.yaml
│   ├── kubelet-config.yaml
│   ├── kube-apiserver.yaml
│   ├── etcd.yaml
│   ├── cni-flannel.conflist
│   ├── haproxy/                (HAProxy master config)
│   ├── registry/               (internal registry config)
│   ├── gcp-instances.yaml
│   └── gcp-firewall-rules.yaml
├── inventory/               ← Ansible inventory snapshot
├── cluster/                 ← misc cluster-level dumps
└── namespaces/              ← 41 namespaces, one folder each
    └── <ns>/
        ├── deployments.yaml
        ├── statefulsets.yaml
        ├── daemonsets.yaml
        ├── cronjobs.yaml
        ├── jobs.yaml
        ├── services.yaml
        ├── ingresses.yaml
        ├── configmaps.yaml
        ├── pvc.yaml
        ├── serviceaccounts.yaml
        ├── rolebindings.yaml
        ├── networkpolicies.yaml
        ├── virtualservices.yaml       (istio)
        └── gateways.yaml              (istio)
```

---

## What is *not* here

This is a **configuration snapshot**, not a dump of running state. The following are intentionally excluded and must be restored from their respective sources:

| Type                          | Where it lives                                     |
| ----------------------------- | -------------------------------------------------- |
| Kubernetes `Secret` contents  | Not exported. Recreate from password manager / SealedSecrets |
| API keys (Groq, OpenAI, …)    | Redacted as `<REDACTED_*>` in configmaps          |
| PVC data (DB rows, artifacts) | **Velero → Cloudflare R2** (`s3://aiot-velero`)    |
| etcd state                    | `etcd-backup` CronJob → R2                         |
| Gitea repositories            | Gitea's own PVC (covered by Velero Kopia FS backup)|
| Mattermost / MLflow DB        | `pg-ha` inside the cluster (covered by Velero)     |
| Container images              | Internal registry (rebuild from Jenkins + Gitea)   |
| Let's Encrypt certificates    | Auto-reissued by cert-manager after rebuild        |

---

## Rebuilding from this repo

High-level sequence to rebuild on new infrastructure:

1. **Provision VMs** (3 GCP + 3 OCI equivalents) — reuse `infra/gcp-instances.yaml` as the spec
2. **Install kubeadm** with `infra/kubeadm-config.yaml`, join workers
3. **Restore etcd** from the latest `etcd-backup` snapshot (optional fast-path; otherwise start fresh)
4. **Apply CRDs and Helm releases** from `cluster-wide/` in order: cert-manager, istio, knative, kubeflow, velero, cnpg, cert-manager ClusterIssuer, ingress-nginx
5. **Apply namespace manifests** from `namespaces/` (re-create Secrets manually first — grep for `<REDACTED>`)
6. **`velero restore create --from-backup <latest>`** to rehydrate CRs and volume data from R2
7. **Re-link Chef / Puppet agents** to the new host IPs; run `puppet agent -t` and `chef-client` to reconverge
8. **Update DNS** — all ingress hostnames are tied to `35.241.255.137.nip.io`; on a new IP, either keep the nip.io pattern or switch to a real DNS zone

---

## Export metadata

- **Exported on**: 2026-04-19 (snapshot of live cluster `aiot2`)
- **Cluster**: Kubernetes v1.32.13, 6 nodes (3 GCP + 3 OCI)
- **GCP project**: `upbeat-sunup-493110-n3` (europe-west1-b)
- **Namespaces captured**: 41
- **Sanitized**: Groq / OpenAI / GitHub / AWS / Slack / HuggingFace / Google API keys and inline `password:` values replaced with `<REDACTED_*>` placeholders

> Re-export is driven from `aiot-master`:
> ```bash
> bash /tmp/export_cluster.sh
> cd ~/aiot-platform && git add -A && git commit -m "snapshot $(date +%F)" && git push
> ```
