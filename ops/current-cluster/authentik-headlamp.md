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
  --from-literal=OIDC_SCOPES='openid profile email offline_access' \
  --from-literal=OIDC_INSECURE_SKIP_VERIFY='true'
```

**CRITICAL: `offline_access` scope is MANDATORY** — without it Authentik will not
issue a refresh token. When the access token expires (1 hour), Headlamp fails to
refresh and sends the user back to the login screen (sign-in loop).

**CRITICAL: `openid` scope is MANDATORY** — without it the OIDC flow does not
produce proper ID tokens.

The chart turns these into the Headlamp args
`-oidc-client-id`, `-oidc-client-secret`, `-oidc-idp-issuer-url`, `-oidc-scopes`.

## Critical: Property mappings MUST be assigned to the provider

**THIS IS THE #1 ROOT CAUSE OF ALL OIDC LOGIN LOOPS.**

Authentik OAuth2 providers need **property mappings** (scope mappings) assigned
to them, otherwise the ID tokens will **not contain any user identity claims**
(email, preferred_username, name, groups). Without these claims, the K3s API
server cannot identify the user and every request fails with:

```
[invalid bearer token, oidc: parse username claims "email": claim not present]
```

### How to check

```bash
kubectl exec -n authentik deploy/authentik-server -- python -c "
import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'authentik.root.settings')
import django; django.setup()
from authentik.providers.oauth2.models import OAuth2Provider
p = OAuth2Provider.objects.get(client_id='headlamp')
print(f'Property mappings: {p.property_mappings.count()}')
for pm in p.property_mappings.all():
    print(f'  - {pm.name}')
"
# Expected output: 3 mappings (email, profile, openid)
```

### How to fix

```bash
kubectl exec -n authentik deploy/authentik-server -- python -c "
import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'authentik.root.settings')
import django; django.setup()
from authentik.providers.oauth2.models import OAuth2Provider, ScopeMapping
p = OAuth2Provider.objects.get(client_id='headlamp')
email_sm = ScopeMapping.objects.get(scope_name='email')
profile_sm = ScopeMapping.objects.get(scope_name='profile')
openid_sm = ScopeMapping.objects.get(scope_name='openid')
p.property_mappings.add(email_sm, profile_sm, openid_sm)
print(f'Fixed: {p.property_mappings.count()} mappings assigned')
"
```

### How to verify the token has claims

```bash
curl -sk -X POST "https://authentik.46.4.123.8.nip.io/application/o/token/" \
  -d "client_id=headlamp&client_secret=<secret>&grant_type=client_credentials&scope=openid+profile+email+offline_access" \
  | python3 -c "import json,sys,base64; d=json.load(sys.stdin);
parts=d['id_token'].split('.');
padded=parts[1]+'='*(4-len(parts[1])%4);
print(sorted(json.loads(base64.urlsafe_b64decode(padded)).keys()))"
# Must include: email, preferred_username, name, groups
```

## Critical: email_verified must be True

The default Authentik email scope mapping hardcodes `email_verified: False`.
K3s by default rejects tokens with unverified emails:

```
[invalid bearer token, oidc: email not verified]
```

Fix (one-time):

```bash
kubectl exec -n authentik deploy/authentik-server -- python -c "
import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'authentik.root.settings')
import django; django.setup()
from authentik.providers.oauth2.models import ScopeMapping
email_sm = ScopeMapping.objects.get(scope_name='email')
email_sm.expression = 'return {\"email\": request.user.email, \"email_verified\": True}'
email_sm.save()
print('Updated email_verified to True')
"
```

## Headlamp version pinning

**DO NOT upgrade Headlamp past v0.41.0 without thorough testing.**

v0.43.0 changed session persistence behavior — the OIDC callback returns 303,
but the session cookie is not set, causing an immediate sign-in loop (every API
request after login returns 401).

If you must upgrade, verify that:
1. `/clusters/main/healthz` returns 200 after login (not 401)
2. The browser shows a session cookie after OIDC callback

## K3s OIDC configuration

The K3s API server must trust Authentik as an OIDC issuer. This is set via
Docker args at container creation (k3d) and **cannot be overridden by config.yaml**.

### Known issues

1. **`oidc-username-claim=email` (hardcoded in Docker args):** K3s uses `email`
   claim for username. If the Authentik property mapping fix above is applied,
   this works. The config.yaml setting is overridden by Docker args.

2. **TLS certificate verification fails:** The K3s container reaches Authentik
   via the Docker bridge network which routes through Traefik (not nginx),
   causing certificate mismatch. Workaround: `oidc-tls-insecure-skip-verify=true`
   in config.yaml (already applied — do not remove).

3. **nginx port conflict with Traefik:** After K3s restart, Traefik's svclb
   DaemonSet takes host ports 80/443 before nginx can bind. Fix:
   ```bash
   kubectl delete daemonset -n kube-system svclb-traefik-*
   kubectl delete svc -n kube-system traefik
   kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
   ```

## Creating missing applications in Authentik

To add all cluster web apps to Authentik (bulk):

```bash
kubectl exec -n authentik deploy/authentik-server -- python -c "
import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'authentik.root.settings')
import django; django.setup()
from authentik.core.models import Application
apps = [
    ('emqx','EMQX Dashboard','https://emqx.46.4.123.8.nip.io/'),
    ('redpanda','Redpanda Console','https://redpanda.46.4.123.8.nip.io/'),
    ('cloudbeaver','CloudBeaver','https://cloudbeaver.46.4.123.8.nip.io/'),
    # ... add more as needed
]
for slug, name, url in apps:
    if not Application.objects.filter(slug=slug).exists():
        Application.objects.create(name=name, slug=slug, meta_launch_url=url)
        print(f'Created: {name}')
"
```

## Troubleshooting flow (quick reference)

When Headlamp shows sign-in loop:

```bash
# 1. Check K3s OIDC errors
docker logs k3d-aiot-hetzner-server-0 2>&1 | grep "Unable to authenticate" | tail -3

# 2. Check Headlamp token errors
kubectl logs -n headlamp deployment/headlamp | grep -iE "error|fail|refresh|token" | tail -10

# 3. Check property mappings (MUST show 3)
kubectl exec -n authentik deploy/authentik-server -- python -c "
import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'authentik.root.settings')
import django; django.setup()
from authentik.providers.oauth2.models import OAuth2Provider
p = OAuth2Provider.objects.get(client_id='headlamp')
print(p.property_mappings.count())
"

# 4. Check secret scopes (MUST include offline_access)
kubectl get secret -n headlamp headlamp-oidc -o jsonpath='{.data.OIDC_SCOPES}' | base64 -d

# 5. Check nginx is running (not Traefik)
kubectl get pods -n ingress-nginx | grep Running
```

## End-to-end checklist

1. Authentik provider `headlamp` has a signing key and the list-form redirect URIs.
2. OIDC discovery endpoint returns HTTP 200 JSON.
3. `headlamp-oidc` Secret exists in the `headlamp` namespace with correct scopes.
4. **Provider has 3 property mappings (email, profile, openid) — CHECK THIS FIRST.**
5. **Email scope mapping has `email_verified: True`.**
6. API server is started with the `--oidc-*` flags (see `ops/current-cluster/k3d-oidc/`).
7. RBAC binds `https://authentik.46.4.123.8.nip.io/application/o/headlamp/#admin`
   to `cluster-admin` (Flux-managed via `apps/headlamp`).
8. Headlamp version is v0.41.0 (not v0.43.0).
9. nginx ingress is running (Traefik svc deleted to avoid port conflict).
10. Browse to `https://headlamp.46.4.123.8.nip.io/`, sign in via Authentik, land
    on the dashboard with no `Forbidden` errors.
