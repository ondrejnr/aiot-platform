# aiot-platform

![Kubernetes](https://img.shields.io/badge/kubernetes-v1.32.13-326ce5?logo=kubernetes&logoColor=white)
![Nodes](https://img.shields.io/badge/nodes-5%20(3%20GCP%20%2B%202%20OCI)-success)
![Namespaces](https://img.shields.io/badge/namespaces-80-blue)
![Backup](https://img.shields.io/badge/velero-Cloudflare%20R2-f38020?logo=cloudflare&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Open--WebUI%20%2B%20RAG-ff6f00)
![K8sGPT](https://img.shields.io/badge/self--monitoring-K8sGPT-purple)
![Config](https://img.shields.io/badge/config-Chef%20%7C%20Puppet%20%7C%20Ansible-red)
![Status](https://img.shields.io/badge/status-production-brightgreen)

> **Industrial AIoT platform** — an end-to-end system for **collecting, storing, and evaluating industrial sensor data with AI and large language models (LLMs)**. Field devices stream telemetry over MQTT, data is persisted and indexed, ML pipelines train and serve predictive-maintenance models, and a RAG-enabled LLM interface lets operators **ask questions about production data in natural language**.

The platform was built to answer practical questions from the shop floor — *"Which machine is drifting out of spec?"*, *"What caused yesterday's anomaly?"*, *"Predict the remaining useful life of pump #12"* — by combining classical ML (trained in Kubeflow, served via KServe) with an LLM layer (Open-WebUI + Qdrant RAG) grounded in the platform's own operational data.

## Why this platform exists

Industrial data is useless unless it becomes a **decision**. AIoT is designed around that chain:

1. **Collect** — MQTT ingestion from sensors and PLCs, retained in a time-series–friendly Postgres (CloudNativePG)
2. **Enrich** — digital-twin service aligns raw telemetry with asset metadata; embeddings stored in Qdrant for semantic retrieval
3. **Learn** — Kubeflow Pipelines train forward-looking models (predictive maintenance v2) on a weekly schedule; MLflow versions every experiment
4. **Serve** — the best model is promoted and served by KServe/Knative with zero-downtime rollout
5. **Ask** — operators and engineers interact with the whole system through an LLM chat (Open-WebUI) that uses RAG over platform data and can call the inference service as a tool

Everything runs on a self-hosted, multi-cloud Kubernetes cluster (GCP + OCI), with **Chef Automate**, **Puppet Enterprise**, and **Ansible/Semaphore** keeping hosts and agents in a known state, and **Velero** guaranteeing disaster recovery to Cloudflare R2.

## Self-operating cluster — K8sGPT

A unique property of this platform is that the cluster **monitors and reasons about itself**. Namespace **`k8sgpt`** runs:

- **K8sGPT Operator** — continuously analyses every namespace for misconfigurations, failing pods, broken probes, stuck PVCs, CrashLoopBackOff patterns, and RBAC gaps
- **LLM-backed diagnostics** — findings are explained in plain English through an LLM (local or Groq), so an alert reads *"pod X is restarting because liveness probe targets an unreachable port — check service `Y`"* instead of a raw Kubernetes event
- **Anomaly detector** (`k8sgpt-anomaly-detector`) — ML-based trend detection over metrics and logs
- **Mattermost bot** (`k8sgpt-mm-bot`) — posts high-severity findings to the `#k8s` channel in Mattermost; engineers reply in the thread and the bot can run follow-up diagnostics
- **Robusta bridge** (`k8sgpt-robusta-bridge`) — forwards events to Robusta for automated playbook execution (restart, scale, cordon, notify) when the diagnosis matches a known remediation
- **Scheduled reports** — `ai-health-report` and `ai-log-analyzer` CronJobs produce daily summaries of cluster health; `monitoring-watchdog` keeps the pipeline itself alive

The result is an **AI-supervised cluster**: the same LLM technology that answers operator questions about production data also watches the Kubernetes control plane and workloads, flags regressions, and can auto-remediate common issues.

```mermaid
flowchart LR
    subgraph K8S["☸️ Kubernetes cluster"]
        EV[/"Events · Logs<br/>Metrics · Probes"/]
    end

    EV --> OP
    subgraph K8SGPT["🤖 K8sGPT namespace"]
        OP["K8sGPT Operator<br/>scans all namespaces"]
        AN["Anomaly Detector<br/>ML on metrics"]
        LLM{{"🧠 LLM<br/>Groq / local"}}
        BR["Robusta bridge<br/>auto-remediation"]
        BOT["Mattermost bot<br/>#k8s channel"]
        RPT["Scheduled reports<br/>ai-health · ai-log"]
    end

    OP --> LLM
    AN --> LLM
    LLM -->|plain English<br/>diagnosis| BOT
    LLM -->|match playbook| BR
    LLM --> RPT
    BR -.restart · scale · cordon.-> K8S
    BOT <==>|human replies| ENG(["👷 Engineers"])

    classDef k8s fill:#dbeafe,stroke:#1d4ed8,color:#1e3a8a
    classDef gpt fill:#f3e8ff,stroke:#7e22ce,color:#581c87
    classDef llm fill:#fef2f2,stroke:#dc2626,color:#7f1d1d
    class EV k8s
    class OP,AN,BR,BOT,RPT gpt
    class LLM llm
```

---

## Platform at a glance

```mermaid
flowchart LR
    subgraph EDGE["🏭 EDGE / FIELD"]
        S1[("📡<br/>Sensors<br/>PLCs")]
        S2[("⚙️<br/>Simulator<br/>(aiot)")]
    end

    subgraph INGEST["📥 INGESTION"]
        MQ[("EMQX<br/>MQTT broker")]
        N8[("n8n<br/>flows")]
        SINK[["pg-sink"]]
    end

    subgraph STORE["🗄️ STORAGE LAYER"]
        PG[("CloudNativePG<br/>pg-ha · 3 replicas")]
        QD[("Qdrant<br/>vectors / RAG")]
    end

    subgraph AI["🧠 AI / ML"]
        KF[["Kubeflow Pipelines<br/>aiot-forward-maintenance-v2"]]
        ML[("MLflow<br/>registry")]
        KS[["KServe<br/>InferenceService"]]
    end

    subgraph LLM["💬 LLM LAYER"]
        OW[["Open-WebUI<br/>chat"]]
        RAG[["rag-worker<br/>+ indexer"]]
    end

    subgraph OPS["🛡️ SELF-OPERATING"]
        KG{{"K8sGPT<br/>AI-supervised cluster"}}
        MM[["Mattermost<br/>#k8s"]]
    end

    S1 & S2 -->|MQTT| MQ
    MQ --> SINK
    N8 --> SINK
    SINK --> PG
    PG --> KF
    KF --> ML
    ML --> KS
    PG --> RAG
    RAG --> QD
    QD --> OW
    KS -.tools.-> OW

    KG -.watches.-> INGEST
    KG -.watches.-> STORE
    KG -.watches.-> AI
    KG -.watches.-> LLM
    KG ==alerts==> MM

    classDef edge fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef ingest fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef store fill:#e0e7ff,stroke:#4f46e5,color:#312e81
    classDef ai fill:#fce7f3,stroke:#db2777,color:#831843
    classDef llm fill:#fef2f2,stroke:#dc2626,color:#7f1d1d
    classDef ops fill:#ecfdf5,stroke:#059669,color:#064e3b
    class S1,S2 edge
    class MQ,N8,SINK ingest
    class PG,QD store
    class KF,ML,KS ai
    class OW,RAG llm
    class KG,MM ops
```

---

## Cluster topology

```mermaid
flowchart TB
    USER(["🌐 Internet users<br/>*.35.241.255.137.nip.io"])

    subgraph GCP["☁️ GCP · europe-west1-b"]
        HA{{"HAProxy<br/>SNI router"}}
        M["🎛️ aiot-master<br/>control-plane<br/>10.132.0.2"]
        W1["⚙️ aiot-worker-01<br/>10.132.0.3<br/>Chef · Puppet · PE"]
        W2["⚙️ aiot-worker-02<br/>10.132.0.4<br/>pg-ha · storage"]
    end

    subgraph OCI["🔶 OCI · eu-frankfurt-1"]
        O1["⚙️ oci-e5-node1<br/>172.16.200.10"]
        O2["⚙️ oci-e5-node2<br/>172.16.200.11<br/>SigNoz · ClickHouse"]
    end

    WG{{"🔐 WireGuard mesh"}}

    USER --> HA
    HA -->|80/443 SNI| W1
    HA -->|80/443 SNI| W2
    HA -->|SSH fallback| M

    M <-.-> W1 & W2
    M <==> WG
    WG <==> O1 & O2

    classDef gcp fill:#e0f2fe,stroke:#0369a1,color:#0c4a6e
    classDef oci fill:#fef3c7,stroke:#ea580c,color:#7c2d12
    classDef tun fill:#f3e8ff,stroke:#9333ea,color:#581c87
    classDef ext fill:#f3f4f6,stroke:#6b7280
    class M,W1,W2,HA gcp
    class O1,O2 oci
    class WG tun
    class USER ext
```

| Node             | Role           | IP (internal)         | OS                | Location              |
| ---------------- | -------------- | --------------------- | ----------------- | --------------------- |
| aiot-master      | control-plane  | 10.132.0.2            | CentOS Stream 9   | GCP `europe-west1-b`  |
| aiot-worker-01   | worker         | 10.132.0.3            | CentOS Stream 9   | GCP `europe-west1-b`  |
| aiot-worker-02   | worker         | 10.132.0.4            | CentOS Stream 9   | GCP `europe-west1-b`  |
| oci-e5-node1     | worker         | 172.16.200.10 (WG)    | Oracle Linux 9.7  | OCI `eu-frankfurt-1`  |
| oci-e5-node2     | worker         | 172.16.200.11 (WG)    | Oracle Linux 9.7  | OCI `eu-frankfurt-1`  |

- **Kubernetes**: v1.32.13 (vanilla kubeadm)
- **CNI**: Cilium 1.16.6 — pod CIDR `10.245.0.0/16`, vxlan overlay (port 8473), kubeProxyReplacement=true, Hubble enabled (migrated from flannel 2026-04-26)
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

```mermaid
flowchart TB
    subgraph HOSTS["🖥️ All 6 cluster nodes"]
        H[" "]
    end

    subgraph PUPPET["🎩 Puppet Enterprise (desired state)"]
        direction LR
        P1["Packages · kernel<br/>sysctl · systemd"]
        P2["Agents: noop=true<br/>Patch Mgmt group"]
    end

    subgraph CHEF["🍴 Chef Automate (compliance)"]
        direction LR
        C1["InSpec scans<br/>Automate reporting"]
        C2["chef-webhook<br/>→ Mattermost + Grafana"]
    end

    subgraph ANS["🟣 Ansible via Semaphore (operations)"]
        direction LR
        A1["Health · uptime · disk"]
        A2["Firewall audit<br/>Reboot planner<br/>Cert check"]
    end

    PUPPET -->|host-level state| H
    CHEF -->|compliance + events| H
    ANS -->|ad-hoc operations| H

    classDef p fill:#fef2f2,stroke:#dc2626,color:#7f1d1d
    classDef c fill:#fff7ed,stroke:#ea580c,color:#7c2d12
    classDef a fill:#faf5ff,stroke:#9333ea,color:#581c87
    classDef h fill:#f1f5f9,stroke:#475569
    class P1,P2 p
    class C1,C2 c
    class A1,A2 a
    class H h
```

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

```mermaid
flowchart LR
    CL["☸️ Cluster<br/>manifests + PVCs"]
    V[["Velero<br/>daily 03:00"]]
    KOPIA[["Kopia<br/>FS backup"]]
    ETCD[["etcd-backup<br/>CronJob"]]
    R2[("☁️ Cloudflare R2<br/>s3://aiot-velero")]
    VUI{{"Velero UI<br/>vui.*"}}

    CL --> V
    CL --> KOPIA
    CL --> ETCD
    V --> R2
    KOPIA --> R2
    ETCD --> R2
    VUI -.browse.-> R2

    R2 ==restore==> NEW["🆕 New cluster<br/>rebuilt from this repo"]

    classDef src fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef tool fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store fill:#ffedd5,stroke:#ea580c,color:#7c2d12
    classDef new fill:#dcfce7,stroke:#16a34a,color:#14532d
    class CL src
    class V,KOPIA,ETCD,VUI tool
    class R2 store
    class NEW new
```

### Velero

- **Target**: Cloudflare R2 bucket `s3://aiot-velero` (S3-compatible, endpoint `*.r2.cloudflarestorage.com`)
- **Schedule** `daily-cluster-backup` (namespace `velero`) — every day at 03:00 UTC, retention 7 days
- **Scope**: all cluster + namespaced Kubernetes objects (manifests, CRs, ConfigMaps, Secrets metadata), excluding ephemeral/log-like resources (`events`, `replicasets.apps`, `nodes`) and noisy namespaces (`kube-system`, `local-path-storage`, `monitoring`, `signoz`, `victoriametrics`, `velero`, `knative-serving`, `opentelemetry-operator-system`)
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



## Installing this cluster on fresh VMs

A complete bootstrap workflow lives in [`install/`](install/) — a numbered set
of idempotent shell scripts that take **brand-new Linux VMs** to a fully
running aiot-platform cluster.

```bash
# === On EVERY node (master + workers) ===
sudo bash install/00-vm-prereqs.sh        # containerd, kubeadm, kubelet, helm

# === On master only ===
sudo bash install/01-init-master.sh       # kubeadm init from infra/kubeadm-config.yaml
                                          # → prints `kubeadm join` token; run on workers

# === On master, after all workers joined ===
sudo bash install/02-cilium.sh            # CNI: Cilium 1.16.6 with stored helm values
sudo bash install/03-platform.sh          # cert-manager + ingress-nginx + local-path
sudo bash install/04-helm-charts.sh       # all 14 helm releases (Rancher, ArgoCD, …)
sudo bash install/05-apply-cluster.sh     # CRDs + cluster-scoped + per-NS manifests

# === Optional: restore Secrets + PVC data ===
export AWS_ACCESS_KEY_ID=…  AWS_SECRET_ACCESS_KEY=…  R2_ENDPOINT=https://….r2.cloudflarestorage.com
export BACKUP_NAME=$(velero backup get -o name | head -1)
sudo bash install/06-velero-restore.sh
```

Or simply:

```bash
make prereqs       # 00
make init          # 01
make all           # 02 → 03 → 04 → 05
make restore       # 06 (optional)
make status        # show health
```

Helm release catalogue (chart, version, repo, values file) is declared in
[`install/helm-charts.csv`](install/helm-charts.csv). Cluster topology
(API endpoints, node CIDR, certs SANs) is declared in
[`infra/kubeadm-config.yaml`](infra/kubeadm-config.yaml). Cilium tuning lives
in [`cluster-wide/helm-values/kube-system_cilium.yaml`](cluster-wide/helm-values/kube-system_cilium.yaml).

See [`install/README.md`](install/README.md) for the full guide, recovery
procedures, and what is **not** in the repo (secrets, WireGuard mesh, external
services).

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
│   ├── cni-cilium.conflist
│   ├── haproxy/                (HAProxy master config)
│   ├── registry/               (internal registry config)
│   ├── gcp-instances.yaml
│   └── gcp-firewall-rules.yaml
├── inventory/               ← Ansible inventory snapshot
├── cluster/                 ← misc cluster-level dumps
└── namespaces/              ← 80 namespaces, one folder each
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
