# Current live-cluster snapshots

This directory records the small set of live objects on `hetzner-new` that are not represented by a Flux `HelmRelease` chart.

These files are **snapshots**, not active Flux resources. They are kept here so the repository describes the whole current cluster state without risking an unintended takeover of manually bootstrapped services.

## Files

| File | Live namespace | Purpose | Notes |
|---|---|---|---|
| `manual-services/authentik.yaml` | `authentik` | Authentik SSO server, worker, Redis and ingress | Secret objects are intentionally omitted. Several GitOps-managed apps depend on `authentik-server.authentik.svc.cluster.local`. |
| `manual-services/chef-automate-proxy.yaml` | `chef` | Kubernetes `Service`/`Endpoints`/`Ingress` proxy to the Docker `chef-automate` container | Endpoint IP is `172.18.0.8` on Docker network `k3d-aiot-hetzner`. Protected by `oauth2-proxy` (Authentik SSO). |
| `manual-services/oauth2-proxy.yaml` | `oauth2-proxy` | Forward-auth gateway putting Authentik SSO in front of apps without native OIDC (chef-automate, cloudbeaver, chaos-theater) | `provider = "oidc"` is required (else it defaults to Google). The Authentik provider must have `grant_types` including `authorization_code`, and its `client_secret` must match the one in `oauth2-proxy.cfg`. See in-file TROUBLESHOOTING. |
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

## Recovery on 2026-09-23

Live repairs and their corresponding manifests are recorded here. After
publishing, reconcile the Flux GitRepository and root Kustomization, then verify
the affected Helm releases against that revision. Authentik and host-service
snapshots remain manually managed; publishing them does not transfer ownership
to Flux.

- Authentik server now mounts a 256 MiB memory-backed `/dev/shm`; its previous
	64 MiB shared memory filled up and caused Gunicorn SIGBUS restarts. The duplicate
	unmanaged `authentik-cert` Certificate was removed, preserving `authentik-tls`.
- Cert-manager HTTP-01 self-checks use public resolvers because the internal Chef
	hostname resolves to its Docker container. Kubeflow solver pods allow their
	public token port 8089, including traffic from the host-network ingress.
	Chef and Kubeflow certificates were renewed through December 22, 2026.
- AWX now separates the image repository from version `24.6.1`. Its operator
	recreated the execution environments successfully.
- Zabbix bootstrap discovers node InternalIPs through the Kubernetes API and uses
	the actual kube-state-metrics Service name. Kubelet CPU discovery includes only
	Running pods; cluster-state monitoring still covers pending and failed pods.
	Missing optional ExternalIP/NetworkUnavailable fields become `Not assigned` /
	`Unknown`, not fabricated healthy values. Checks for absent optional server
	collectors and unsupported Alpine package inventory are disabled with reasons.
- Terrakube uses its declared resource limits; Tensorboard controller limits are
	250m for manager and 100m for kube-rbac-proxy. Katib and Tensorboard Flux
	Kustomizations also received the local patches on the live cluster.
- Alloy's stale recovery ConfigMap was removed from the local Kustomize source.
	During recovery, the live `observability-logs/alloy` ConfigMap was protected with
	`kustomize.toolkit.fluxcd.io/reconcile=disabled` and
	`kustomize.toolkit.fluxcd.io/prune=disabled`. Keep these until the published
	source no longer manages that ConfigMap and its old inventory is cleared;
	Helm must remain its only configuration owner. Alloy receives logs and traces,
	and forwards OTLP metrics to VictoriaMetrics. Grafana uses OTLP gRPC port 4317.
	During recovery, the live Alloy HelmRelease temporarily overrode
	`spec.values.alloy.alloy.configMap.content` with the repaired chart content so
	drift correction cannot restore the old trace-only configuration. Remove that
	override after publishing and reconciling the repaired chart, then verify all
	five receivers again. Startup API log replay can produce Loki 400 responses
	for historical entries outside retention or its out-of-order ingestion window;
	those entries are not recovered by this repair. Fresh log ingestion was tested.

### Katib webhook trust

The generated `kubeflow/katib-webhook-cert` contains a self-signed public
`tls.crt`, valid until June 2036. Its `ca.crt` was populated from that certificate
and `cert-manager.io/allow-direct-injection=true` added. Webhooks use
`cert-manager.io/inject-ca-from-secret: kubeflow/katib-webhook-cert`; Flux patches
remove the upstream placeholder CA bundle so cainjector owns the live bundle.
If this manually generated Secret is replaced, repeat the CA initialization
after verifying the replacement is still self-signed; never commit its key:

```sh
kubectl get secret katib-webhook-cert -n kubeflow -o json |
	jq '{metadata:{annotations:{"cert-manager.io/allow-direct-injection":"true"}},data:{"ca.crt":.data["tls.crt"]}}' |
	kubectl patch secret katib-webhook-cert -n kubeflow --type=merge --patch-file=/dev/stdin
kubectl run katib-admission-check -n kubeflow --image=busybox:1.36 --restart=Never --dry-run=server -o name
```

### Host Puppet Enterprise services

`pe-puppetserver` previously relied on a forking launcher whose global process
lookup collided with other Puppet JVMs. The host override at
`/etc/systemd/system/pe-puppetserver.service.d/override.conf` now contains:

```ini
[Service]
Type=simple
PIDFile=
User=pe-puppet
Group=pe-puppet
ExecStart=
ExecStart=/opt/puppetlabs/server/apps/puppetserver/bin/puppetserver foreground
ExecStop=
ExecReload=
KillMode=control-group
StandardOutput=journal
StandardError=journal
TimeoutStartSec=300
```

Runtime directories under `/opt/puppetlabs/server/data/puppetserver`,
`/opt/puppetlabs/server/apps/puppetserver/tmp`, `/var/log/puppetlabs/puppetserver`
and `/run/puppetlabs/puppetserver` must be writable by `pe-puppet`.
The manually launched host JVM was stopped before starting the systemd unit;
do not use a broad process-name kill that could affect Kubernetes workloads.

In `/etc/puppetlabs/nginx/conf.d/proxy.conf`, console proxy_pass/proxy_redirect
use `http://localhost:4430`, not port 44430. SAML uses
`https://127.0.0.1:4431`, not `0.0.0.0:44431`. These match console-services'
webserver configuration. Validate nginx configuration before restarting.
Both services are enabled and managed by systemd; host nginx remains on
8080/4443 without taking Docker's 80/443 ports. Puppet status on
`https://127.0.0.1:8140/status/v1/simple` returned `running` and the console
on HTTPS 4443 returned its expected login redirect.
