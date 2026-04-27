# Installing on a fresh cluster (GitOps)

This is the **GitOps install path**. Everything beyond the bootstrap layer
is reconciled by ArgoCD from this repository.

## Prerequisites

- 3+ Linux VMs (RHEL 9 / Rocky 9 / Ubuntu 22.04+), 4 vCPU / 8 GB RAM each
- Static IPs and a reachable shared network
- DNS or `/etc/hosts` for `argocd.<your-domain>`
- An age key generated locally (do **not** commit the private part):
  ```bash
  age-keygen -o age.key
  # public:  age1xxxxx... → put in secrets/.sops.yaml
  # private: keep on the install host, pass via AGE_KEY_FILE env
  ```

## Bootstrap order

Run on the **first control-plane node** as a sudo-capable user:

```bash
git clone https://github.com/ondrejnr/aiot-platform.git
cd aiot-platform

# 1. OS prereqs (containerd, kubelet, kubeadm, kubectl, helm)
sudo bash bootstrap/00-vm-prereqs.sh

# 2. Initialise the control plane (Flannel CNI; podSubnet 10.244.0.0/16)
sudo bash bootstrap/01-kubeadm-init.sh

# 3. Install Flannel CNI v0.27.4
sudo bash bootstrap/02-flannel.sh

# 4. sealed-secrets controller (for non-sops secrets)
bash bootstrap/03-sealed-secrets.sh

# 5. sops + age binaries + age key as Secret in argocd ns
AGE_KEY_FILE=$HOME/age.key bash bootstrap/04-sops-age.sh

# 6. ArgoCD with KSOPS plugin
bash bootstrap/05-argocd.sh

# 7. Apply the App-of-Apps root — ArgoCD takes over from here
bash bootstrap/06-bootstrap-app.sh
```

After step 7, ArgoCD reconciles:

1. `argocd/projects/all.yaml` — 7 AppProjects with namespace allow-lists
2. `argocd/bootstrap/argocd-self.yaml` — ArgoCD self-manages from `apps/argocd`
3. `argocd/applications/<project>/*.yaml` — every helm release in `apps/`
4. `argocd/applications/_namespaces-appset.yaml` — ApplicationSet that
   re-applies the snapshot manifests under `namespaces/<ns>/` for everything
   that isn't a helm release

## Joining worker nodes

`bootstrap/01-kubeadm-init.sh` prints the `kubeadm join` command. Run on each
worker after `00-vm-prereqs.sh`:

```bash
sudo bash bootstrap/00-vm-prereqs.sh
sudo kubeadm join <CP_IP>:6443 --token <T> --discovery-token-ca-cert-hash sha256:<H>
```

## Repository layout

```
.
├── bootstrap/                   # 7 ordered shell scripts (run once per cluster)
├── infra/
│   └── kubeadm-config.yaml      # InitConfiguration + ClusterConfiguration + KubeletConfiguration
├── argocd/
│   ├── bootstrap/
│   │   ├── root-app.yaml        # App-of-Apps entry point
│   │   └── argocd-self.yaml
│   ├── projects/all.yaml        # 7 AppProjects
│   └── applications/
│       ├── platform/            # cert-manager, ingress-nginx, k8up, ...
│       ├── monitoring/          # prometheus, signoz, victoriametrics, ...
│       ├── rancher/             # rancher, fleet, turtles
│       ├── data/                # cnpg, qdrant, redis, mattermost, zabbix
│       ├── ci-cd/               # argocd, jenkins, gitea
│       ├── platform-mgmt/       # headlamp, karpor
│       └── _namespaces-appset.yaml  # ApplicationSet over namespaces/
├── apps/                        # 1 umbrella chart per release (Chart.yaml + values.yaml)
├── secrets/                     # sops+age encrypted Secrets (.sops.yaml present)
├── clusters/
│   └── aiot2-prod/values.yaml   # cluster-specific overrides (domain, R2 endpoint, ...)
├── cluster-wide/                # snapshot of CRDs, helm-values dump, sc/pv/...
├── namespaces/                  # snapshot of every namespace's manifests
└── _legacy/install/             # old non-GitOps install scripts (kept for reference)
```

## Day-2

| Task | How |
|---|---|
| Deploy a new helm app | Create `apps/<name>/{Chart.yaml,values.yaml}` + `argocd/applications/<project>/<name>.yaml` |
| Add a secret | `sops --encrypt --in-place secrets/<ns>/<name>.yaml` |
| Bump a chart version | Edit `apps/<name>/Chart.yaml` `dependencies[0].version` |
| Override per-cluster | Add `valueFiles: [values.yaml, ../../clusters/<env>/values.yaml]` to the Application |
| Disaster recovery | k8up restic restores from R2 (see top-level `README.md` Backup section) |

---

## Post-install manual steps

After all ArgoCD Applications reach `Synced/Healthy`, the following items
require human intervention (cannot be in git):

### 1. Required Secrets (encrypt with sops + commit, OR provide manually)

| Path | Purpose | How to get it |
|---|---|---|
| `secrets/k8up-system/r2-creds.yaml` | k8up backup target (Cloudflare R2) | Cloudflare dashboard → R2 → Manage API tokens |
| `secrets/etcd-backup/r2-credentials.yaml` | etcd snapshot CronJob | Same R2 token, namespaced |
| `secrets/argocd/repo-creds.yaml` | ArgoCD private git repo access (if private) | GitHub PAT or SSH deploy key |
| `secrets/cattle-system/bootstrap.yaml` | Rancher initial admin password | Pre-set OR read from `kubectl get secret bootstrap-secret -n cattle-system` after first start |
| `secrets/jenkins/admin.yaml` | Jenkins admin user override | Generate (default chart auto-generates) |
| `secrets/gitea/admin.yaml` | Gitea admin user override | Pre-decided values |
| `secrets/aiot/groq-api-key.yaml` | Groq LLM proxy | https://console.groq.com/keys |
| `secrets/k8sgpt/llm-keys.yaml` | k8sgpt providers (OpenAI/Groq/etc.) | Provider dashboards |
| `secrets/auth/dex-passwords.yaml` | Dex static users | bcrypt-hash chosen passwords |

Encrypt:
```bash
age-keygen -o age.key
# Copy public key (age1...) into secrets/.sops.yaml
sops --encrypt --in-place secrets/<ns>/<file>.yaml
```

### 2. Cluster-specific config to verify

- `clusters/aiot2-prod/values.yaml` — domain, storageClass, R2 endpoint
- `infra/kubeadm-config.yaml` — `certSANs` list (your IPs/hostnames)
- `apps/rancher/values.yaml` — `hostname`, `bootstrapPassword`
- `apps/cert-manager/values.yaml` — add ClusterIssuer email for Let's Encrypt
- `apps/dex/values.yaml` — `issuer` URL, static users via secret reference

### 3. Snapshot replay caveats

The ApplicationSet `_namespaces-appset.yaml` re-applies snapshot manifests for
54 namespaces (ai-enricher, aiot, chef, emqx, konflux-*, tekton-pipelines,
istio-system, knative-serving, kubeflow, registry, ...). These were captured
from the live cluster and may contain:
- Image tags pinned to specific versions (update via PR if needed)
- Service account tokens that won't resolve on a fresh cluster (apps will
  recreate them on first start)
- `nodeSelector`/`affinity` rules referencing old node names — review and
  adjust per cluster

### 4. External integrations to re-establish

- **Cloudflare R2** — bucket `aiot-velero` (or create new), provide creds via secrets above
- **GitHub repo deploy key** — if cloning private images
- **DNS A records** — point `*.<your-domain>` at the cluster's external IP
  (or use nip.io for testing)
- **Mattermost webhook** — Jenkins notifications (`mattermost-webhook` cred)
- **Gitea webhooks** — for Jenkins multibranch + Konflux PaC

### 5. Things this repo does NOT install

- HCP Terraform workspaces (separate `aiot-infra` repo)
- Habitat builder (separate `chef`/`habitat` repos)
- VPN/WireGuard — manage outside cluster
- Cluster registration in Rancher UI — done manually after Rancher starts

### 6. Verify install

```bash
kubectl get application -n argocd
kubectl get applicationset -n argocd
helm ls -A
kubectl get pv,pvc -A | grep -v Bound | grep -v 'STATUS\|CAPACITY' || echo "all PVs bound"
```

