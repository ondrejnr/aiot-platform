# Install / restore notes for the current cluster

The active production-like cluster is **`hetzner-new`** on Hetzner (`46.4.123.8`) and runs k3d/k3s with Flux.

This file replaces the old kubeadm/GCP install notes. The old `bootstrap/`, `infra/`, `namespaces/`, `cluster-wide/` and `manifests/` content remains in the repository only as historical reference and is not the current install path.

## Current source of truth

- GitHub mirror: `git@github.com:ondrejnr/aiot-platform.git`
- Internal Flux source: `http://gitea-http.gitea.svc.cluster.local:3000/aiot-iac/aiot-platform.git`
- Host checkout: `/root/aiot-platform`
- Active Flux path: `flux/clusters/hetzner-new`
- Active charts: `apps/*`

## Bootstrap model

The current cluster was bootstrapped as k3d/k3s on one Hetzner host:

- k3d server: `k3d-aiot-hetzner-server-0`
- k3d agents: `k3d-aiot-hetzner-agent-0..3`
- Docker network: `k3d-aiot-hetzner`
- public domain suffix: `*.46.4.123.8.nip.io`
- Flux: `v2.6.4`

A fresh rebuild should recreate the k3d cluster, bootstrap Flux to `flux/clusters/hetzner-new/flux-system`, point Flux at the internal Gitea repository, and then let Flux reconcile `apps/*`.

## API server OIDC (required for Headlamp SSO)

The Kubernetes API server must trust Authentik as an OIDC issuer, otherwise the
ID token Headlamp forwards to the API is rejected with `401` and SSO fails. This
is a host-level k3s setting, not a Flux resource, so it has to be re-applied on
every cluster rebuild. Full details and the exact `--k3s-arg` / `config.yaml`
form are in [`ops/current-cluster/k3d-oidc/`](ops/current-cluster/k3d-oidc/).

Minimal apply on the running cluster:

```bash
docker cp ops/current-cluster/k3d-oidc/server-config.yaml \
  k3d-aiot-hetzner-server-0:/etc/rancher/k3s/config.yaml
docker restart k3d-aiot-hetzner-server-0
```

The matching RBAC (OIDC identity -> `cluster-admin`) and the Headlamp OIDC client
args are Flux-managed in the `apps/headlamp` overlay chart. The `headlamp-oidc`
Secret (OIDC client id/secret/issuer/scopes) is created out-of-band in the
`headlamp` namespace and is referenced by the chart as an external secret; see
[`ops/current-cluster/authentik-headlamp.md`](ops/current-cluster/authentik-headlamp.md).

## Day-2 workflow

```bash
cd /root/aiot-platform

git status --short
helm template aiot-ml-platform apps/aiot-ml-platform >/tmp/aiot-ml-platform.yaml
flux get all -A
flux reconcile source git flux-system
flux reconcile ks flux-system
```

For one release:

```bash
flux reconcile hr <release> -n <namespace> --force
```

## Non-Flux runtime snapshots

Some live services are intentionally captured as snapshots under `ops/current-cluster/manual-services/` instead of being actively reconciled by Flux:

- `authentik` SSO runtime objects, secrets omitted
- `chef` Kubernetes ingress/service/endpoints proxy to the external Docker `chef-automate` container
- `loadtest/emqtt-bench-pub`, currently scaled to zero

Do not apply these snapshots blindly. They are meant to document the live cluster and help recovery planning.

## Safety rules

- Do not use the old GCP/OCI topology from older docs.
- Do not start `loadtest/emqtt-bench-pub` before pipeline changes are verified and the pipeline is drained.
- Avoid `kubectl describe` and unmasked `helm get values --all` on this cluster because they can print secrets.
- Push GitOps changes to both GitHub and internal Gitea, because Flux reads Gitea.
