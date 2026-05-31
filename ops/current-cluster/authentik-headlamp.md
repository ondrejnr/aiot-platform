# Authentik OAuth2 provider for Headlamp

Headlamp authenticates users via Authentik using the OpenID Connect (OIDC)
Authorization Code flow. Authentik runs as a manual service on `hetzner-new`
(see `ops/current-cluster/manual-services/authentik.yaml`), so its OAuth2
provider configuration lives in the Authentik database, not in Flux. This file
documents the exact provider/application settings that the Flux-managed Headlamp
chart and the API server OIDC config depend on.

## Application and provider

- Application slug: `headlamp` (name "Headlamp"), launch URL `https://headlamp.46.4.123.8.nip.io/`
- Provider: OAuth2/OpenID provider named `headlamp`
- Client type: confidential
- Client ID: `headlamp`
- Signing key: any valid certificate (e.g. "authentik Internal JWT Certificate").
  Without a signing key the discovery endpoint and token signing fail.

### Redirect URIs

Authentik 2026.5.x stores redirect URIs as a JSON **list** of objects with a
`matching_mode`. Both callback paths are allowed so the deployment works with
native Headlamp OIDC (`/oidc-callback`) and, if ever reintroduced, an
oauth2-proxy front (`/oauth2/callback`):

```json
[
  {"url": "https://headlamp.46.4.123.8.nip.io/oidc-callback",  "matching_mode": "strict"},
  {"url": "https://headlamp.46.4.123.8.nip.io/oauth2/callback", "matching_mode": "strict"}
]
```

The currently active client is native Headlamp OIDC, which uses `/oidc-callback`.

## Pitfall: `_redirect_uris` must be a JSON list, not a JSON string

If `_redirect_uris` is set (e.g. from a migration or a hand-written `ak shell`
snippet) to a **JSON-encoded string** instead of a real Python/JSON list, the
OIDC discovery endpoint
(`/application/o/headlamp/.well-known/openid-configuration`) returns **HTTP 500**
with `MissingValueError: missing value for field "matching_mode"`, and every
client (Headlamp, oauth2-proxy, the API server OIDC plugin) fails to initialize.

Correct (value is a list):

```python
from authentik.providers.oauth2.models import OAuth2Provider
p = OAuth2Provider.objects.get(name="headlamp")
p._redirect_uris = [
    {"url": "https://headlamp.46.4.123.8.nip.io/oidc-callback",  "matching_mode": "strict"},
    {"url": "https://headlamp.46.4.123.8.nip.io/oauth2/callback", "matching_mode": "strict"},
]
p.save()
```

Verify the discovery endpoint returns JSON (HTTP 200):

```bash
curl -sk https://authentik.46.4.123.8.nip.io/application/o/headlamp/.well-known/openid-configuration \
  | python3 -m json.tool | head
```

## headlamp-oidc Secret

The Headlamp chart references an external Secret `headlamp-oidc` in the
`headlamp` namespace (`apps/headlamp/values.yaml` -> `headlamp.config.oidc.externalSecret`).
It carries the client credentials and issuer. Recreate it after a rebuild
(client secret is taken from the Authentik provider):

```bash
kubectl create secret generic headlamp-oidc -n headlamp \
  --from-literal=OIDC_CLIENT_ID=headlamp \
  --from-literal=OIDC_CLIENT_SECRET='<authentik headlamp provider client secret>' \
  --from-literal=OIDC_ISSUER_URL=https://authentik.46.4.123.8.nip.io/application/o/headlamp/ \
  --from-literal=OIDC_SCOPES='profile email'
```

The chart turns these into the Headlamp args
`-oidc-client-id`, `-oidc-client-secret`, `-oidc-idp-issuer-url`, `-oidc-scopes`.

## End-to-end checklist

1. Authentik provider `headlamp` has a signing key and the list-form redirect URIs.
2. OIDC discovery endpoint returns HTTP 200 JSON.
3. `headlamp-oidc` Secret exists in the `headlamp` namespace.
4. API server is started with the `--oidc-*` flags (see `ops/current-cluster/k3d-oidc/`).
5. RBAC binds `https://authentik.46.4.123.8.nip.io/application/o/headlamp/#admin`
   to `cluster-admin` (Flux-managed via `apps/headlamp`).
6. Browse to `https://headlamp.46.4.123.8.nip.io/`, sign in via Authentik, land
   on the dashboard with no `Forbidden` errors.
