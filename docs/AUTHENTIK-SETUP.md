# Authentik SSO Setup for AIOT Platform

This document describes the complete Authentik OIDC and SAML configuration for the AIOT platform, enabling passwordless login across Kubernetes dashboards, CI/CD, and application services.

**Date:** June 2, 2026  
**Status:** Production  
**Deployed Version:** Authentik 2026.5.2  
**Cluster:** hetzner-new (k3d/k3s)  
**Domain:** `*.46.4.123.8.nip.io`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Authentik Server Setup](#authentik-server-setup)
3. [OAuth2-Proxy Setup](#oauth2proxy-setup)
4. [Application Integration](#application-integration)
5. [Known Issues & Fixes](#known-issues--fixes)
6. [Deployment Checklist](#deployment-checklist)
7. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

AIOT platform uses a **layered authentication model**:

```
User Browser
     ↓
Ingress-NGINX (reverse proxy)
     ↓
OAuth2-Proxy (forward-auth gate at ingress level)
     ↓
Authentik (OIDC/SAML SSO authority)
     ↓
Backend Services (Headlamp, Jenkins, Gitea, Chef, etc.)
```

### Components

| Component | Namespace | Purpose | Notes |
|-----------|-----------|---------|-------|
| **Authentik** | `authentik` | SSO server, OAuth2/OIDC provider, SAML IdP | Manual deployment, not Flux-managed |
| **oauth2-proxy** | `oauth2-proxy` | OIDC forward-auth middleware for ingress | Filters unauthenticated requests |
| **Ingress-NGINX** | `ingress-nginx` | Kubernetes ingress controller | Apply server-snippet for buffer tuning |
| **Dex** | `dex` | OIDC helper connector (optional) | Used for extra routing flexibility |

### Authentication Flows

#### Flow 1: OAuth2-Proxy (Forward-Auth)
- User requests `https://service.46.4.123.8.nip.io/`
- Ingress routes to oauth2-proxy via `nginx.ingress.kubernetes.io/auth-url` annotation
- oauth2-proxy checks for valid `_oauth2_proxy` cookie
- If missing → redirect to Authentik `/application/o/authorize/`
- User authenticates → Authentik returns ID token + refresh token
- oauth2-proxy stores in secure cookie, forwards to backend

#### Flow 2: OIDC Direct (Apps with Native OIDC)
- Headlamp, Jenkins configured with Authentik OIDC provider
- App redirects to Authentik `/application/o/<app>/.well-known/openid-configuration`
- User authenticates → app receives ID token
- App stores in session; Kubernetes API server trusts Authentik issuer (OIDC configuration)

#### Flow 3: SAML (Chef Automate)
- Chef Automate native SAML + Dex connector
- Chef → Dex → Authentik (SAML IdP)
- Authentik returns signed SAML response
- Dex relays to Chef → user logged in

---

## Authentik Server Setup

### Deployment

**Location:** `ops/current-cluster/manual-services/authentik.yaml`

```bash
# Apply Authentik manifests (non-Flux, manual management)
kubectl apply -f ops/current-cluster/manual-services/authentik.yaml
```

**Important Notes:**
- Authentik is **NOT managed by Flux** (no `kustomization.yaml` or Helm release)
- Secrets (passwords, certificates) are stored separately
- Live patches to ConfigMaps/Deployments persist across reconciliation

### Database & Cache

Authentik uses PostgreSQL (part of the manifest) for data store:
- Username: `authentik` (or specified in secret)
- Cache backend: Django PostgreSQL cache (no Redis required)
- Broker: None (async tasks handled by workers)

### Certificates

Authentik generates a self-signed certificate automatically:
- Path: `/certs/tls.crt` and `/certs/tls.key` inside container
- Issuer: `authentik 2026.5.2`
- Used for:
  - HTTPS serving on port 443
  - SAML response signing (Chef Automate)
  - OIDC token signing

**Critical:** When rebuilding the cluster, Authentik's self-signed cert changes. All applications referencing the old cert will fail token validation.

### Initial Admin User

Default credentials (set at first boot):
- Username: `admin@localhost`  
- Password: Set via environment or web UI

**Location in manifest:** Check `authentik.yaml` for `AUTHENTIK_BOOTSTRAP_TOKEN` or admin creation steps.

---

## OAuth2-Proxy Setup

### Deployment

**Location:** `ops/current-cluster/manual-services/oauth2-proxy.yaml`  
**Source of configuration:** Kubernetes Secret `oauth2-proxy` (NOT ConfigMap `oauth2-proxy-config`)

### Key Environment Variables

```yaml
OIDC_ISSUER_URL: https://authentik.46.4.123.8.nip.io/application/o/oauth2-proxy/
OIDC_CLIENT_ID: oauth2-proxy
OIDC_CLIENT_SECRET: <from secret>
REDIRECT_URL: https://oauth2-proxy.46.4.123.8.nip.io/oauth2/callback
COOKIE_DOMAINS: [ ".46.4.123.8.nip.io" ]
COOKIE_REFRESH: "1h"
SESSION_STORE_TYPE: redis
REDIS_URL: redis://redis.oauth2-proxy:6379
```

### Critical Configuration

**Cookie Domain Must Be Wildcard:**
```yaml
cookie_domains = [ ".46.4.123.8.nip.io" ]
```

If using host-only cookies (e.g., `oauth2-proxy.46.4.123.8.nip.io`), the session cookie won't be sent to other subdomains (Chef, Jenkins, Gitea, Headlamp), causing login loops.

**Whitelist & Scopes:**
```yaml
whitelist_domains: [ ".46.4.123.8.nip.io" ]
scopes: [ "openid", "email", "profile" ]
```

---

## Application Integration

> **Chef Automate → Habitat Builder:** Samostatný sprievodca v [HABITAT-BUILDER-CHEF-AUTOMATE-SSO.md](HABITAT-BUILDER-CHEF-AUTOMATE-SSO.md) – rieši preklik z Applications sekcie v Chef Automate

### 1. Headlamp (Kubernetes Dashboard)

**OIDC Type:** Native OIDC + RBAC binding  
**Location:** `apps/headlamp/values.yaml`

#### Configuration

```yaml
oidcRbac:
  enabled: true
  bindings:
    - name: headlamp-oidc-admin
      clusterRole: cluster-admin
      subjectKind: User
      # Format: <issuer-url>#<username-from-preferred_username-claim>
      subject: "https://authentik.46.4.123.8.nip.io/application/o/headlamp/#admin"

headlamp:
  config:
    inCluster: true
    oidc:
      externalSecret:
        enabled: true
        name: headlamp-oidc
      issuerURL: https://authentik.46.4.123.8.nip.io/application/o/headlamp/
      clientID: headlamp
      clientSecret: <from-secret>
      scopes: "openid email profile"
```

#### Authentik Provider Setup

In Authentik web UI or via Django shell:

```python
from authentik.core.models import Application
from authentik.oauth2_provider.models import OAuth2Provider, ClientTypes, GrantTypes

# Create OAuth2Provider for Headlamp
provider = OAuth2Provider.objects.create(
    name="headlamp",
    client_id="headlamp",
    client_secret="<generated-secret>",
    client_type=ClientTypes.CONFIDENTIAL,
    redirect_uris="https://headlamp.46.4.123.8.nip.io/oidc/callback",
    access_token_validity="minutes=5",
    refresh_token_validity="days=30",
)
provider.grant_types = [GrantTypes.AUTHORIZATION_CODE, GrantTypes.REFRESH_TOKEN]
provider.save()

# Link to Application
app = Application.objects.get(slug="headlamp")
app.provider = provider
app.save()
```

#### Kubernetes API Server OIDC

The Kubernetes API server itself trusts Authentik as an OIDC issuer, allowing token validation:

**In k3s config** (`/etc/rancher/k3s/`):
```bash
--oidc-issuer-url=https://authentik.46.4.123.8.nip.io/application/o/headlamp/
--oidc-client-id=headlamp
--oidc-username-claim=preferred_username
--oidc-groups-claim=groups
--oidc-ca-file=/etc/ssl/certs/authentik-ca.crt  # Self-signed cert
```

**Important:** The CA certificate from Authentik must be added to the API server's trusted store.

---

### 2. Jenkins (CI/CD)

**OIDC Type:** Native OIDC via `oic-auth` plugin  
**Location:** `apps/jenkins/values.yaml`

#### Configuration

```yaml
jenkins:
  controller:
    installPlugins:
      - oic-auth
    additionalExistingSecrets:
      - name: jenkins-oidc  # Contains clientId, clientSecret
```

#### Secret: `jenkins-oidc`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: jenkins-oidc
  namespace: jenkins
stringData:
  clientId: jenkins
  clientSecret: <from-authentik>
  clientSecret2: <from-authentik>  # optional backup
```

#### Authentik Provider Setup

```python
from authentik.oauth2_provider.models import OAuth2Provider

provider = OAuth2Provider.objects.create(
    name="jenkins",
    client_id="jenkins",
    client_secret="<secret>",
    client_type=ClientTypes.CONFIDENTIAL,
    redirect_uris="https://jenkins.46.4.123.8.nip.io/securityRealm/finishLogin",
)
provider.grant_types = [GrantTypes.AUTHORIZATION_CODE, GrantTypes.REFRESH_TOKEN]
provider.save()

app = Application.objects.get(slug="jenkins")
app.provider = provider
app.save()
```

#### Jenkins OIDC Configuration

Managed by JCasC (Jenkins Configuration as Code), stored in ConfigMap or during initialization:

```yaml
unclassified:
  location:
    url: https://jenkins.46.4.123.8.nip.io/
  oic:
    clientId: jenkins
    clientSecret: ${JENKINS_OIC_SECRET}
    wellKnownOpenIDConfigurationUrl: https://authentik.46.4.123.8.nip.io/application/o/jenkins/.well-known/openid-configuration
    tokenServerUrl: https://authentik.46.4.123.8.nip.io/application/o/token/
    authorizationServerUrl: https://authentik.46.4.123.8.nip.io/application/o/authorize/
    userNameField: preferred_username
    userFullNameFieldName: name
    groupsClaimName: groups
```

---

### 3. Gitea (Git Repository)

**OIDC Type:** OAuth2 source (not OIDC-native, but compatible)  
**Location:** `apps/gitea/values.yaml`

#### Authentik Provider Setup

```python
provider = OAuth2Provider.objects.create(
    name="gitea",
    client_id="gitea",
    client_secret="<secret>",
    client_type=ClientTypes.CONFIDENTIAL,
    redirect_uris="https://gitea.46.4.123.8.nip.io/user/oauth2/Authentik/callback",
)
```

**Note:** Redirect URI path includes provider name with **capital A** in "Authentik"—must match exactly.

#### Gitea OAuth Source Setup

```bash
# Inside Gitea pod, add OAuth2 provider
kubectl exec -n gitea <pod> -c gitea -- \
  gitea admin auth add-oauth \
  --name Authentik \
  --provider openidConnect \
  --key <client-id> \
  --secret <client-secret> \
  --auto-discover-url https://authentik.46.4.123.8.nip.io/application/o/gitea/.well-known/openid-configuration \
  --scopes "openid email profile"
```

#### Gitea Web UI OAuth

Users click "Sign in with Authentik" → redirected to Authentik → after auth redirected back to Gitea with auth code → Gitea exchanges for ID token → logged in.

---

### 4. Chef Automate (Infrastructure Automation)

**OIDC Type:** SAML via Dex → Authentik  
**Location:** `ops/current-cluster/manual-services/chef-automate-proxy.yaml`  
**⚠️ Kompletný návod:** [`CHEF-AUTOMATE-SAML-AUTHENTIK.md`](CHEF-AUTOMATE-SAML-AUTHENTIK.md) — obsahuje všetky nástrahy a riešenia!

#### Architecture

```
Chef UI (backend port 443)
  ↓ (User clicks "Sign in with SAML")
Dex connector (SAML connector)
  ↓ (SAMLRequest → Authentik)
Authentik SAML IdP
  ↓ (SAMLResponse signed)
Dex → /dex/callback
  ↓
User logged in → IAM policy check → Dashboard
```

#### Kľúčové súbory (v Docker kontajneri)

| Súbor | Účel |
|-------|------|
| `/etc/chef-automate/dex/saml-ca.pem` | SAML certifikát (mimo hab) |
| `/hab/svc/automate-dex/var/etc/config.yml` | Dex config (immutable) |
| `/etc/chef-automate/dex/start-saml-dex.sh` | Startup skript |
| `/etc/systemd/system/dex-saml.service` | Systemd service |

#### ⚠️ Najčastejšie chyby

1. **"Requested resource does not exist"** — Dex config nemá `connectors` sekciu
2. **"no attribute with name email"** — Atribúty musia byť v URI formáte (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress`)
3. **"It looks like you do not have permission"** — IAM politika nesedí na SAML identifikátory (viď sekciu 4 v CHEF-AUTOMATE-SAML-AUTHENTIK.md)
4. **Habitat prepisuje súbory** — certifikát musí byť mimo `/hab/svc/`, config musí byť immutable

#### Dex SAML Connector (finálna funkčná verzia)

```yaml
connectors:
  - type: saml
    id: saml
    name: SAML
    config:
      ssoURL: https://authentik.46.4.123.8.nip.io/application/saml/chef-automate/sso/binding/post/
      ca: /etc/chef-automate/dex/saml-ca.pem
      redirectURI: https://chef.46.4.123.8.nip.io/dex/callback
      entityIssuer: authentik
      usernameAttr: http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name
      emailAttr: http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress
      groupsAttr: http://schemas.xmlsoap.org/claims/Group
      nameIDPolicyFormat: emailAddress
```

#### IAM Policy (oprávnenia)

```bash
# Vytvorenie admin tokenu
chef-automate iam token create admin-token --admin

# Vytvorenie SAML Admins politiky
curl -sk -X POST -H "api-token: $TOKEN" \
  https://localhost/apis/iam/v2/policies \
  -d '{
    "name": "SAML Admins",
    "id": "saml-admins",
    "members": [
      "user:saml:akadmin@example.com",
      "team:saml:authentik Admins"
    ],
    "statements": [{"effect": "ALLOW", "role": "owner", "projects": ["*"]}],
    "projects": []
  }'
```

---

## Known Issues & Fixes

### Issue 1: Login Loop in Headlamp

**Symptom:**
```
User authenticates successfully in Authentik
→ Redirected back to Headlamp
→ Headlamp login page reappears
→ Loop repeats
```

**Root Cause:**
NGINX ingress-nginx has undersized buffers (default 4KB for `proxy_buffer_size`). Authentik's OAuth2 ID token with embedded `Set-Cookie` headers exceeds this limit, causing NGINX to return `400 Bad Request` or truncate headers. Headlamp doesn't receive the session cookie → login loop.

**Error Message (ingress-nginx logs):**
```
upstream sent too big header while reading response header from upstream
```

**Fix:**

Apply annotation to all affected ingresses to increase buffer sizes:

```bash
# Headlamp
kubectl -n headlamp annotate ingress headlamp \
  nginx.ingress.kubernetes.io/server-snippet="proxy_buffer_size 32k; proxy_buffers 8 32k;" \
  --overwrite

# Alternatively, use proxy-buffer-size + proxy-buffers-number annotations:
kubectl -n headlamp annotate ingress headlamp \
  nginx.ingress.kubernetes.io/proxy-buffer-size=16k \
  nginx.ingress.kubernetes.io/proxy-buffers-number=4 \
  --overwrite
```

**Verification:**
```bash
# Check annotation is applied
kubectl -n headlamp get ingress headlamp -o jsonpath="{.metadata.annotations}"

# Check ingress-nginx pod is updated
kubectl -n ingress-nginx logs -l app.kubernetes.io/name=ingress-nginx | grep proxy_buffer
```

After applying, restart your browser session (clear cookies) and test login flow again.

---

### Issue 2: Certificate Validation Failures

**Symptom:**
```
Headlamp pod cannot reach Authentik OIDC endpoint
curl: (60) SSL certificate problem: self signed certificate
OpenID configuration endpoint returns 0 bytes
```

**Root Cause:**
Authentik uses a self-signed certificate. Application pods don't have Authentik's CA certificate in their trusted store (`/etc/ssl/certs/`), causing TLS validation to fail.

**Fix:**

Option A: Inject CA into pod via ConfigMap

```bash
# Export Authentik certificate
kubectl -n authentik exec -i deployment/authentik-server -- \
  openssl s_client -connect localhost:443 -showcerts < /dev/null 2>/dev/null | \
  openssl x509 -text > /tmp/authentik-ca.crt

# Create ConfigMap
kubectl create configmap authentik-ca-bundle --from-file=/tmp/authentik-ca.crt -n headlamp

# Mount in Headlamp deployment
# Add to spec.template.spec:
#   volumes:
#   - name: authentik-ca
#     configMap:
#       name: authentik-ca-bundle
#   containers[0]:
#     volumeMounts:
#     - name: authentik-ca
#       mountPath: /etc/ssl/certs/authentik-ca.crt
#       subPath: authentik-ca.crt
```

Option B: Use `--insecure-skip-verify` for debugging (NOT production)

```bash
# In Headlamp pod environment:
OIDC_INSECURE_SKIP_VERIFY=true
```

---

### Issue 3: Redirect Loop in oauth2-proxy

**Symptom:**
```
User clicks "Sign in"
→ oauth2-proxy redirects to Authentik
→ User authenticates
→ Redirected back to oauth2-proxy callback
→ Returns 401 Unauthorized
→ Redirects back to /oauth2/start
→ Back to login page (infinite loop)
→ Browser shows "about:blank" or hanging page
```

**Root Cause:**
oauth2-proxy secret uses host-only cookie domains (e.g., `oauth2-proxy.46.4.123.8.nip.io`). After authentication, the `_AUTH` session cookie is not sent to other subdomains (e.g., `chef.46.4.123.8.nip.io`), so oauth2-proxy rejects the request.

**Error (oauth2-proxy logs):**
```
Couldn't validate cookie, so returning a 401. upstream client returned unsuccessful status code: 401
```

**Fix:**

Update oauth2-proxy Secret to use wildcard domain:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: oauth2-proxy
  namespace: oauth2-proxy
type: Opaque
stringData:
  config.cfg: |
    ...
    cookie_domains = [ ".46.4.123.8.nip.io" ]  # Add this line
    whitelist_domains = [ ".46.4.123.8.nip.io" ]
    ...
```

Then restart the deployment:

```bash
kubectl rollout restart deploy -n oauth2-proxy oauth2-proxy
```

**Verification:**
Check that cookies now have domain=`.46.4.123.8.nip.io`:

```bash
# During login flow, inspect cookies:
curl -v https://oauth2-proxy.46.4.123.8.nip.io/oauth2/auth 2>&1 | grep "Set-Cookie"
# Expected: Set-Cookie: _oauth2_proxy_csrf=...; Domain=.46.4.123.8.nip.io; Path=/; HttpOnly; Secure
```

---

### Issue 4: Chef Automate 405 (Invalid SAML Binding)

**Symptom:**
```
User clicks "Sign in" in Chef
→ Dex redirects to Authentik SAML endpoint
→ HTTP 405 Method Not Allowed returned
```

**Root Cause (Post-Rebuild Scenario):**
After rebuilding the cluster, Authentik doesn't have the SAML provider for Chef. Instead, an old OAuth2Provider entry remains (from a previous setup migration). Authentik returns 405 because no SAML provider is registered.

Additionally, Chef's `ca_contents` points to the old Authentik self-signed certificate. After cluster rebuild, Authentik generates a new certificate with a different issuer. Token validation would fail even if the SAML provider existed.

**Fix:**

1. **Create SAMLProvider for Chef (see [Chef Automate](#4-chef-automate-infrastructure-automation) section above)**

2. **Update Chef Dex config with new Authentik certificate:**

```bash
# Export new Authentik cert
kubectl -n authentik exec -i deployment/authentik-server -- \
  cat /certs/tls.crt > /tmp/authentik-new-ca.crt

# Create patch file
cat > /tmp/chef-saml-patch.toml <<'EOF'
[dex.v1.sys.connectors.saml]
ca_contents = """-----BEGIN CERTIFICATE-----
<PASTE FULL CERT HERE>
-----END CERTIFICATE-----"""
EOF

# Apply patch to Chef
docker exec chef-automate chef-automate config patch /tmp/chef-saml-patch.toml

# Restart Dex
docker exec chef-automate systemctl restart chef-automate-dex
```

---

## Deployment Checklist

When deploying AIOT platform with Authentik on a **new cluster**, follow this sequence:

- [ ] **Cluster prerequisites:**
  - [ ] K3s/k3d with ingress-nginx deployed
  - [ ] cert-manager installed (for Let's Encrypt certificates)
  - [ ] Storage classes available (nfs, local-path)

- [ ] **Authentik server:**
  - [ ] Apply `ops/current-cluster/manual-services/authentik.yaml`
  - [ ] Wait for Authentik pod to be running
  - [ ] Check `/etc/authentik/config.yml` is mounted correctly
  - [ ] Authenticate to Authentik web UI (https://authentik.46.4.123.8.nip.io)

- [ ] **Bootstrap Authentik providers (run setup script or manual):**
  - [ ] Create OAuth2Provider for `headlamp` (OIDC)
  - [ ] Create OAuth2Provider for `jenkins` (OIDC)
  - [ ] Create OAuth2Provider for `gitea` (OAuth2)
  - [ ] Create SAMLProvider for `chef-automate` (SAML)
  - [ ] Assign providers to respective Applications
  - [ ] Create authorization flows (implicit consent preferred)
  - [ ] Set default authentication flow (password + MFA rules)

- [ ] **oauth2-proxy:**
  - [ ] Apply `ops/current-cluster/manual-services/oauth2-proxy.yaml`
  - [ ] Verify Secret contains:
    - [ ] `cookie_domains = [ ".46.4.123.8.nip.io" ]`
    - [ ] Correct Authentik OIDC credentials
  - [ ] Wait for oauth2-proxy pod running

- [ ] **Kubernetes API Server OIDC:**
  - [ ] Add Authentik CA cert to k3s trusted store
  - [ ] Configure k3s with `--oidc-*` flags
  - [ ] Restart API server
  - [ ] Test: `kubectl auth can-i get pods --as=<oidc-user>`

- [ ] **Application configurations:**
  - [ ] **Headlamp:**
    - [ ] Deploy `apps/headlamp/values.yaml` via Flux
    - [ ] Verify OIDC secret created
    - [ ] Test login: https://headlamp.46.4.123.8.nip.io/signin
  - [ ] **Jenkins:**
    - [ ] Deploy `apps/jenkins/values.yaml` with OIDC secret
    - [ ] Configure JCasC with well-known endpoint
    - [ ] Test: Jenkins login → Authentik → back to Jenkins
  - [ ] **Gitea:**
    - [ ] Deploy `apps/gitea/values.yaml`
    - [ ] Manually add OAuth2 source via `gitea admin auth add-oauth`
    - [ ] Test login from web UI
  - [ ] **Chef Automate:**
    - [ ] Deploy Chef via Docker/manual process
    - [ ] Create SAMLProvider in Authentik
    - [ ] Configure Dex SAML connector in Chef
    - [ ] Test: Chef login → Authentik SAML → back to Chef

- [ ] **Ingress annotations:**
  - [ ] Apply buffer-size annotations to all ingresses (fix Issue 1)
  - [ ] Verify `nginx.ingress.kubernetes.io/proxy-buffer-size` applied

- [ ] **Testing:**
  - [ ] Test each application login flow end-to-end
  - [ ] Verify session cookies have wildcard domain
  - [ ] Check token expiration & refresh behavior
  - [ ] Monitor logs for OIDC/SAML errors

- [ ] **Documentation:**
  - [ ] Record any custom settings (domain, certificate, secrets)
  - [ ] Document any deviations from this guide
  - [ ] Save provider IDs and client_ids for future rebuilds

---

## Troubleshooting

### Login Testing Script

A Python script to test OIDC flow end-to-end:

```python
#!/usr/bin/env python3
"""
Test OIDC login flow for AIOT services
Usage: python3 flowtest.py --service headlamp --user admin@localhost --password xxx
"""

import requests
import json
import sys
from urllib.parse import urlparse, parse_qs
import argparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def session_with_retries():
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def test_oidc_flow(service_url, user, password):
    """Test OIDC flow from service to Authentik and back."""
    session = session_with_retries()
    session.verify = False  # Self-signed cert
    
    print(f"[*] Starting OIDC test for {service_url}")
    
    # Step 1: Access service login (oauth2-proxy or app-native)
    print(f"[+] GET {service_url}/signin")
    resp = session.get(f"{service_url}/signin", allow_redirects=False)
    print(f"    Status: {resp.status_code}")
    
    # Step 2: Follow redirect chain to Authentik
    while 'location' in resp.headers:
        location = resp.headers['location']
        print(f"[->] {location}")
        resp = session.get(location, allow_redirects=False)
        print(f"    Status: {resp.status_code}")
        if 'authentik' in location:
            break
    
    # Step 3: Authenticate to Authentik
    if '/login' in resp.text or 'username' in resp.text:
        print(f"[*] Posting credentials to Authentik")
        # Example: form submission (adjust selectors per app)
        resp = session.post(
            resp.url,
            data={'username': user, 'password': password},
            allow_redirects=False
        )
        print(f"    Status: {resp.status_code}")
    
    # Step 4: Follow post-auth redirects back to service
    while 'location' in resp.headers and 'authentik' in resp.headers['location']:
        location = resp.headers['location']
        print(f"[->] {location}")
        resp = session.get(location, allow_redirects=False)
        print(f"    Status: {resp.status_code}, Content-Length: {len(resp.content)}")
    
    # Step 5: Final check
    if resp.status_code == 200 and len(resp.content) > 1000:
        print(f"[✓] SUCCESS: Logged in to {service_url}")
        return True
    else:
        print(f"[✗] FAILED: Status {resp.status_code}, Content {len(resp.content)} bytes")
        print(f"    Location header: {resp.headers.get('location', 'None')}")
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--service', required=True, help='Service URL base (e.g., https://headlamp.46.4.123.8.nip.io)')
    parser.add_argument('--user', default='admin')
    parser.add_argument('--password', required=True)
    
    args = parser.parse_args()
    success = test_oidc_flow(args.service, args.user, args.password)
    sys.exit(0 if success else 1)
```

**Usage:**
```bash
python3 flowtest.py \
  --service https://headlamp.46.4.123.8.nip.io \
  --user admin@localhost \
  --password <authentik-admin-password>
```

### Common Debug Commands

```bash
# Check Authentik is running
kubectl -n authentik get pods
kubectl -n authentik logs -f deployment/authentik-server

# Check oauth2-proxy
kubectl -n oauth2-proxy get pods
kubectl -n oauth2-proxy logs -f deployment/oauth2-proxy

# Export Authentik certificate for inspection
kubectl -n authentik exec -i deployment/authentik-server -- \
  openssl x509 -in /certs/tls.crt -text -noout | grep -E "Issuer|Subject"

# Test OIDC endpoint reachability
curl -sk https://authentik.46.4.123.8.nip.io/application/o/headlamp/.well-known/openid-configuration | jq .

# Check ingress annotations
kubectl get ingress -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.metadata.annotations.nginx\.ingress\.kubernetes\.io\/proxy-buffer-size}{"\n"}{end}'

# Tail ingress-nginx error log
kubectl -n ingress-nginx logs -f -l app.kubernetes.io/name=ingress-nginx | grep -E "upstream|buffer|header"

# Test oauth2-proxy cookie domain
curl -vsk https://oauth2-proxy.46.4.123.8.nip.io/oauth2/auth 2>&1 | grep "Set-Cookie"
# Expected: Set-Cookie: ... Domain=.46.4.123.8.nip.io ...
```

### Application-Specific Debugging

**Headlamp:**
```bash
# Check OIDC secret exists
kubectl -n headlamp get secret headlamp-oidc -o jsonpath='{.data.oidc-issuer-url}' | base64 -d

# Check API server OIDC config
ps aux | grep kube-apiserver | grep oidc
```

**Jenkins:**
```bash
# Check OIC plugin logs
kubectl -n jenkins logs -f pod/jenkins-0 | grep -i "oic\|openid\|well-known"
```

**Gitea:**
```bash
# Check OAuth source registered
kubectl -n gitea exec -i pod/gitea-0 -c gitea -- \
  gitea admin auth list
```

**Chef:**
```bash
# Check SAML connector config
docker exec chef-automate chef-automate config show | grep -A10 "saml"

# Check Dex logs
docker logs chef-automate-dex | grep -i saml
```

---

## Important Notes for Future Cluster Rebuilds

1. **Flux-Managed vs Manual Deployment:**
   - Applications (Headlamp, Jenkins, Gitea) are deployed via Flux (GitOps)
   - Authentik, oauth2-proxy, Chef are **manual deployments** (NOT Flux-managed)
   - Live patches to these manual services **persist** across Flux reconciliation
   - Next cluster rebuild: re-apply authentik.yaml and oauth2-proxy.yaml

2. **Certificate Rotation:**
   - Authentik auto-generates a self-signed cert on first boot
   - After cluster rebuild, the cert changes (new issuer fingerprint)
   - Update references in:
     - Chef Dex config (`ca_contents`)
     - Kubernetes API server (`--oidc-ca-file`)
     - Any applications with pinned certificate thumbprints

3. **Secret Management:**
   - OAuth2Provider client secrets are stored in Authentik database
   - Backup Authentik database (`authentik` PostgreSQL) before cluster rebuild
   - Or manually recreate providers post-rebuild (see Deployment Checklist)

4. **Bootstrap Automation:**
   - Consider creating a `bootstrap/authentik-providers.py` or `bootstrap/authentik-setup.sh` script
   - Automate provider creation, flow assignment, and app linking
   - Call this script in the post-deployment workflow

---

## References

- [Authentik Documentation](https://docs.goauthentik.io/)
- [OAuth2-Proxy Documentation](https://oauth2-proxy.github.io/)
- [Kubernetes OIDC Configuration](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#openid-connect-tokens)
- [NGINX Ingress Controller Annotations](https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations/)
