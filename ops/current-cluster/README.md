# Current live-cluster snapshots

This directory records the small set of live objects on `hetzner-new` that are not represented by a Flux `HelmRelease` chart.

These files are **snapshots**, not active Flux resources. They are kept here so the repository describes the whole current cluster state without risking an unintended takeover of manually bootstrapped services.

## Files

| File | Live namespace | Purpose | Notes |
|---|---|---|---|
| `manual-services/authentik.yaml` | `authentik` | Authentik SSO server, worker, Redis and ingress | Secret objects are intentionally omitted. Several GitOps-managed apps depend on `authentik-server.authentik.svc.cluster.local`. |
| `manual-services/chef-automate-proxy.yaml` | `chef` | Kubernetes `Service`/`Endpoints`/`Ingress` proxy to the Docker `chef-automate` container | Endpoint IP is `172.18.0.8` on Docker network `k3d-aiot-hetzner`. |
| `manual-services/loadtest-emqtt-bench.yaml` | `loadtest` | Optional MQTT benchmark publisher | Kept scaled to `0`. Before any pipeline change, keep this stopped unless running a controlled load test. |

## Host-level / SSO configuration

These are not Kubernetes snapshots but cluster-bootstrap and SSO settings that
must survive a rebuild and are not captured by any Flux `HelmRelease`:

| Path | Purpose |
|---|---|
| `k3d-oidc/` | k3s API server OIDC flags (trust Authentik as issuer) and how to apply them on rebuild or fresh `k3d cluster create`. Required for Headlamp SSO. |
| `authentik-headlamp.md` | Authentik OAuth2 provider settings for Headlamp (redirect URIs, signing key, the `_redirect_uris` list-vs-string pitfall) and the `headlamp-oidc` Secret. |


## Active GitOps source of truth

The active Flux-managed source remains:

- `apps/*` — Helm umbrella charts.
- `flux/clusters/hetzner-new/apps/*.yaml` — Flux `HelmRelease`/`Kustomization` objects.
- `flux/clusters/hetzner-new/flux-system/` — Flux bootstrap.

Historical exports under `namespaces/`, `cluster-wide/` and `manifests/` are legacy references from older clusters and are not the active source of truth for `hetzner-new`.
