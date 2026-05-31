# k3s API server OIDC configuration

The `hetzner-new` cluster authenticates Headlamp (and any other OIDC client that
talks to the Kubernetes API directly) by trusting **Authentik** as an OIDC
issuer. This is a host-level / cluster-bootstrap setting, not a Flux resource,
so it must be re-applied whenever the k3d/k3s cluster is recreated.

## Why this is required

Headlamp uses the in-cluster proxy with `auth_type: oidc`. The OIDC **ID token**
that the browser obtains from Authentik is forwarded to the Kubernetes API
server. Without the flags below, the API server has no way to validate that
token and every request fails with `401 Unauthorized` (which, in older Headlamp
versions, also manifests as a login/redirect loop on `/clusters/main/healthz`).

## Configuration

The k3d server container reads `/etc/rancher/k3s/config.yaml`. The OIDC issuer is
served by the in-cluster Authentik over the public ingress hostname, so the flags
reference the external issuer URL.

`config.yaml` (inside `k3d-aiot-hetzner-server-0`, persisted on the server node):

```yaml
kube-apiserver-arg:
  - "oidc-issuer-url=https://authentik.46.4.123.8.nip.io/application/o/headlamp/"
  - "oidc-client-id=headlamp"
  - "oidc-username-claim=preferred_username"
  - "oidc-groups-claim=groups"
```

The same content is kept in this repository at
[`server-config.yaml`](./server-config.yaml).

## Apply on an existing cluster

```bash
docker cp ops/current-cluster/k3d-oidc/server-config.yaml \
  k3d-aiot-hetzner-server-0:/etc/rancher/k3s/config.yaml
docker restart k3d-aiot-hetzner-server-0
```

After the restart, confirm the OIDC authenticator initialized (no more
`oidc authenticator: initializing plugin` errors once Authentik is reachable):

```bash
docker logs k3d-aiot-hetzner-server-0 2>&1 | grep -i oidc | tail
```

A healthy state shows the apiserver running with the four `--oidc-*` flags and no
recurring `oidc: authenticator not initialized` messages.

## Apply during a fresh k3d bootstrap

When recreating the cluster with `k3d cluster create`, pass the same flags via
`--k3s-arg`, scoped to the server:

```bash
k3d cluster create aiot-hetzner \
  --k3s-arg "--kube-apiserver-arg=oidc-issuer-url=https://authentik.46.4.123.8.nip.io/application/o/headlamp/@server:*" \
  --k3s-arg "--kube-apiserver-arg=oidc-client-id=headlamp@server:*" \
  --k3s-arg "--kube-apiserver-arg=oidc-username-claim=preferred_username@server:*" \
  --k3s-arg "--kube-apiserver-arg=oidc-groups-claim=groups@server:*" \
  # ... remaining cluster flags ...
```

> Authentik must be reachable at the issuer URL for the apiserver OIDC plugin to
> finish initialization. On a cold rebuild, the apiserver will keep retrying and
> will succeed once Authentik's server pod is Ready and its OAuth2 provider has a
> valid signing key.

## RBAC

The OIDC identity only gets cluster permissions through RBAC. Because the
username claim is `preferred_username` (not `email`), the API server prefixes the
username with `<issuer-url>#`, so the Kubernetes user for the Authentik `admin`
account is:

```
https://authentik.46.4.123.8.nip.io/application/o/headlamp/#admin
```

That binding is Flux-managed in the Headlamp overlay chart
(`apps/headlamp/templates/oidc-rbac.yaml`, configured via `oidcRbac` in
`apps/headlamp/values.yaml`).
