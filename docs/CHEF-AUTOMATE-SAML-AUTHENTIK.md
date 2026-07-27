# Chef Automate SAML + Authentik — Kompletný návod

> **Dátum:** 2026-07-27  
> **Verzia:** 2.0 (po 2-dňovom debugovaní)  
> **IP:** `46.4.123.8`, domény `*.46.4.123.8.nip.io`  
> **Chef Automate:** Docker kontajner `chef-automate` (jrei/systemd-ubuntu:20.04)  
> **Authentik:** 2025.10.4, K8s namespace `authentik`

---

## 0. Rýchly štart — od čistej inštalácie

### 0.1 Čo musí bežať predtým

- [x] **Authentik** v K8s (namespace `authentik`), dostupný na `https://authentik.46.4.123.8.nip.io`
- [x] **Chef Automate** Docker kontajner, dostupný na `https://chef.46.4.123.8.nip.io`
- [x] **K8s ingress** pre Chef Automate (Service + Endpoints + Ingress v namespace `chef`)
- [x] Admin prístup do Authentiku (`admin` / `000000Aa`)

### 0.2 Postup krok za krokom

| # | Krok | Sekcia |
|---|------|--------|
| 1 | Vytvor SAML provider v Authentiku | [2.2](#22-vytvorenie-providera-ak-neexistuje) |
| 2 | Extrahuj SAML certifikát z Authentiku | [2.3](#23-extrakcia-saml-certifikátu) |
| 3 | Zastav hab Dex a zapíš certifikát | [3.1](#31-riešenie-manuálny-dex--immutable-súbory) |
| 4 | Vytvor config.yml so SAML connectorom | [3.1 krok 3](#krok-3-vytvoriť-configyml-so-saml-connectorom) |
| 5 | Zamkni config a spusti Dex manuálne | [3.1 krok 4-5](#krok-4-zamknúť-config-immutable) |
| 6 | Otestuj prihlásenie na `https://chef.46.4.123.8.nip.io/` | — |
| 7 | Vytvor IAM politiku pre SAML používateľa | [4.3](#43-oprava--vytvorenie-saml-politiky) |
| 8 | Nainštaluj systemd service pre trvalosť | [5](#5-trvalé-riešenie-prežitie-reštartu-kontajnera) |

### 0.3 Spustenie Chef Automate kontajnera (referenčný príklad)

```bash
docker run -d \
  --name chef-automate \
  --privileged \
  --network k3d-aiot-hetzner \
  --ip 172.18.0.9 \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  jrei/systemd-ubuntu:20.04

# Po prvom spustení:
docker exec chef-automate bash -c '
sysctl -w vm.max_map_count=262144
echo "chef.46.4.123.8.nip.io" > /etc/hostname
hostname chef.46.4.123.8.nip.io

# Inštalácia Chef Automate
curl -s https://packages.chef.io/files/current/latest/chef-automate-cli/chef-automate_linux_amd64.zip \
  | gunzip - > /usr/local/bin/chef-automate
chmod +x /usr/local/bin/chef-automate

# Nasadenie
chef-automate deploy /etc/chef-automate/config.toml --skip-preflight --accept-terms-and-mlsa -y
'
```

### 0.4 config.toml (minimálny)

```toml
[global.v1]
  fqdn = "chef.46.4.123.8.nip.io"
  [[global.v1.frontend_tls]]
    # TLS certifikát — môže byť self-signed, Let's Encrypt rieši ingress
    cert = """..."""
    key = """..."""

[deployment.v1]
  [deployment.v1.svc]
    channel = "current"
    upgrade_strategy = "at-once"
    deployment_type = "local"

[license_control.v1]
  [license_control.v1.svc]
    license = ""  # licencia sa aplikuje neskôr cez chef-automate license apply
```

---

## 1. Architektúra

```
Prehliadač → https://chef.46.4.123.8.nip.io
  → Chef Automate nginx (port 443)
    → /dex/auth?client_id=automate-session
      → Dex (port 10117) → SAML connector
        → Authentik SAML IdP
          → Prihlásenie (admin / 000000Aa)
        ← SAMLResponse (podpísaná)
      ← /dex/callback → session cookie
    ← Dashboard
```

### Kľúčové komponenty

| Komponent | Umiestnenie | Port |
|-----------|-------------|------|
| **Dex** | `/hab/pkgs/chef/automate-dex/0.1.0/20260604110710/bin/dex` | 10117 (HTTPS), 10116 (gRPC) |
| **Dex config** | `/hab/svc/automate-dex/var/etc/config.yml` | — |
| **Dex template** | `/hab/pkgs/chef/automate-dex/0.1.0/20260604110710/templates/config.yml` | — |
| **SAML cert** | `/etc/chef-automate/dex/saml-ca.pem` | — |
| **Startup skript** | `/etc/chef-automate/dex/start-saml-dex.sh` | — |
| **Systemd service** | `/etc/systemd/system/dex-saml.service` | — |
| **IAM API** | `https://localhost/apis/iam/v2/policies` | — |

---

## 2. Authentik — SAML Provider

### 2.1 Overenie existujúceho providera

```bash
AUTH_POD=$(kubectl get pods -n authentik -l app.kubernetes.io/name=authentik -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n authentik $AUTH_POD -- ak shell -c "
from authentik.providers.saml.models import SAMLProvider
from authentik.core.models import Application

apps = Application.objects.filter(provider__isnull=False)
for app in apps:
    provider = app.provider
    if hasattr(provider, 'samlprovider'):
        saml = provider.samlprovider
        print(f'App: {app.slug}')
        print(f'  ACS URL: {saml.acs_url}')
        print(f'  Issuer: {saml.issuer}')
        print(f'  SP Binding: {saml.sp_binding}')
        print(f'  Cert: {saml.signing_kp.name}')
"
```

Očakávaný výstup:
```
App: chef-automate
  ACS URL: https://chef.46.4.123.8.nip.io/dex/callback
  Issuer: authentik
  SP Binding: post
  Cert: authentik Self-signed Certificate
```

### 2.2 Vytvorenie providera (ak neexistuje)

Spusti cez Authentik Django shell:

```bash
AUTH_POD=$(kubectl get pods -n authentik -l app.kubernetes.io/name=authentik -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n authentik $AUTH_POD -- ak shell -c "
from authentik.core.models import Application
from authentik.flows.models import Flow
from authentik.crypto.models import CertificateKeyPair
from authentik.providers.saml.models import SAMLProvider, SAMLPropertyMapping

AUTHENTIK_URL = 'https://authentik.46.4.123.8.nip.io'
CHEF_URL = 'https://chef.46.4.123.8.nip.io'

app, _ = Application.objects.get_or_create(
    slug='chef-automate',
    defaults={'name': 'Chef Automate', 'meta_launch_url': CHEF_URL},
)

cert = CertificateKeyPair.objects.get(name='authentik Self-signed Certificate')
flow = Flow.objects.get(slug='default-provider-authorization-implicit-consent')

provider, created = SAMLProvider.objects.update_or_create(
    name='chef-automate',
    defaults={
        'authorization_flow': flow,
        'acs_url': f'{CHEF_URL}/dex/callback',
        'issuer': 'authentik',
        'sp_binding': 'post',
        'signing_kp': cert,
        'name_id_mapping': 'emailAddress',
    },
)

# Prirad property mappings (Name, Email, Groups)
mappings = SAMLPropertyMapping.objects.filter(
    name__in=[
        'authentik default SAML Mapping: Username',
        'authentik default SAML Mapping: Email',
        'authentik default SAML Mapping: Name',
        'authentik default SAML Mapping: Groups',
    ]
)
provider.property_mappings.set(mappings)
provider.save()

app.provider = provider
app.save()

print(f'Provider: {provider.name}, created={created}')
print(f'ACS: {provider.acs_url}')
print(f'Issuer: {provider.issuer}')
print(f'Mappings: {[m.name for m in provider.property_mappings.all()]}')
"
```

### 2.3 Extrakcia SAML certifikátu

```bash
AUTH_POD=$(kubectl get pods -n authentik -l app.kubernetes.io/name=authentik -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n authentik $AUTH_POD -- ak shell -c "
from authentik.crypto.models import CertificateKeyPair
cert = CertificateKeyPair.objects.get(name='authentik Self-signed Certificate')
print(cert.certificate_data)
" | grep -A100 "BEGIN CERTIFICATE"
```

---

## 3. Dex SAML Connector — Konfigurácia

### ⚠️ KRITICKÉ UPOZORNENIE: Habitat Supervisor prepisuje súbory!

Chef Automate používa **Habitat Supervisor**, ktorý pri každom reštarte služby:
1. **Prepíše** `config.json` z interného ring-u
2. **Prepíše** `saml-ca.pem` (ak je v config adresári)
3. **Re-renderuje** `config.yml` z template + `config.json`

**Preto NEMOŽNO len upraviť súbory — musia byť chránené!**

### 3.1 Riešenie: Manuálny Dex + immutable súbory

#### Krok 1: Zastaviť hab-managed Dex

```bash
docker exec chef-automate hab svc stop chef/automate-dex
docker exec chef-automate pkill -9 dex
```

#### Krok 2: Uložiť certifikát mimo hab kontroly

```bash
docker exec chef-automate mkdir -p /etc/chef-automate/dex
# Zapíš certifikát z kroku 2.3 do /etc/chef-automate/dex/saml-ca.pem
```

#### Krok 3: Vytvoriť config.yml so SAML connectorom

```yaml
# /hab/svc/automate-dex/var/etc/config.yml
issuer: https://chef.46.4.123.8.nip.io/dex
enablePasswordDB: true
storage:
  type: postgres
  config:
    host: 127.0.0.1
    port: 10145
    database: dex
    user: dex
    ssl:
      mode: verify-ca
      certFile: /hab/svc/automate-dex/config/service.crt
      keyFile: /hab/svc/automate-dex/config/service.key
      caFile: /hab/svc/automate-dex/config/root_ca.crt
web:
  https: 127.0.0.1:10117
  tlsCert: /hab/svc/automate-dex/config/service.crt
  tlsKey: /hab/svc/automate-dex/config/service.key
grpc:
  addr: 127.0.0.1:10116
  tlsCert: /hab/svc/automate-dex/config/service.crt
  tlsKey: /hab/svc/automate-dex/config/service.key
  tlsClientCA: /hab/svc/automate-dex/config/root_ca.crt
staticClients:
  - id: automate-api
    name: Automate API
    public: true
  - id: automate-session
    secret: secretchangeme
    redirectURIs:
      - /signin
    name: Automate Session Service
connectors:
  - type: saml
    id: saml
    name: SAML
    config:
      ssoURL: https://authentik.46.4.123.8.nip.io/application/saml/chef-automate/sso/binding/post/
      ca: /etc/chef-automate/dex/saml-ca.pem          # ← mimo hab kontroly!
      redirectURI: https://chef.46.4.123.8.nip.io/dex/callback
      entityIssuer: authentik                          # ← MUSÍ sedieť s Authentik provider issuer!
      # ⚠️ Atribúty MUSIA byť v URI formáte (Authentik ich posiela takto):
      usernameAttr: http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name
      emailAttr: http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress
      groupsAttr: http://schemas.xmlsoap.org/claims/Group
      nameIDPolicyFormat: emailAddress
oauth2:
  responseTypes: [code, token, id_token]
  skipApprovalScreen: true
  alwaysShowLoginScreen: false
expiry:
  signingKeys: 6h
  idTokens: 3m
invalidLoginAttempts:
  enableInvalidLoginAttempts: true
  blockedDurationInMinutes: 30
  maxInvalidLoginAttemptsAllowed: 5
frontend:
  dir: /hab/pkgs/chef/automate-dex/0.1.0/20260604110710/web
  issuer: Chef Automate
  theme: chef
  extra:
    showDisclosure: false
    disclosureMessage: ""
    showBanner: false
    bannerMessage: ""
    bannerBackgroundColor: "#3864f2"
    bannerTextColor: "#FFFFFF"
```

#### Krok 4: Zamknúť config (immutable)

```bash
docker exec chef-automate chattr +i /hab/svc/automate-dex/var/etc/config.yml
```

#### Krok 5: Spustiť Dex manuálne

```bash
docker exec chef-automate bash -c '
nohup /hab/pkgs/chef/automate-dex/0.1.0/20260604110710/bin/dex serve \
  /hab/svc/automate-dex/var/etc/config.yml > /tmp/dex-manual.log 2>&1 &
'
```

#### Overenie:
```bash
docker exec chef-automate grep "config connector: saml" /tmp/dex-manual.log
# Musí vrátiť: config connector: saml
```

---

## 4. IAM Oprávnenia — ⚠️ NAJČASTEJŠIA CHYBA!

### 4.1 Problém

SAML autentifikácia prebehne úspešne, ale používateľ vidí:
> "It looks like you do not have permission to access any data in Automate."

**Príčina:** Chef Automate IAM robí **presný string matching** na SAML identifikátory. Politika očakáva iný email/skupinu než posiela Authentik.

### 4.2 Diagnostika

```bash
# 1. Zisti, čo presne posiela Authentik
docker exec chef-automate grep "login successful" /tmp/dex-manual.log | tail -1
# Výstup: login successful: connector "saml", username="Admin",
#          email="akadmin@example.com", groups=["authentik Admins"]

# 2. Zisti, čo očakáva IAM politika
docker exec chef-automate bash -c '
TOKEN=$(chef-automate iam token create diag-token --admin 2>&1 | tail -1)
curl -sk -H "api-token: $TOKEN" https://localhost/apis/iam/v2/policies/administrator-access \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('\n'.join(d['policy']['members']))"
'
```

### 4.3 Oprava — Vytvorenie SAML politiky

Vytvor admin token (ak ešte neexistuje):
```bash
docker exec chef-automate chef-automate iam token create admin-token --admin
```

Vytvor politiku s presnými identifikátormi z Authentiku:
```bash
TOKEN="<token>"
curl -sk -X POST -H "api-token: $TOKEN" -H "Content-Type: application/json" \
  https://localhost/apis/iam/v2/policies \
  -d '{
    "name": "SAML Admins",
    "id": "saml-admins",
    "members": [
      "user:saml:akadmin@example.com",
      "team:saml:authentik Admins"
    ],
    "statements": [{
      "effect": "ALLOW",
      "role": "owner",
      "projects": ["*"]
    }],
    "projects": []
  }'
```

**Dôležité:** `members` MUSIA presne sedieť:
- `user:saml:<email>` — email z Authentik SAML response
- `team:saml:<group_name>` — presný názov skupiny z Authentiku

### 4.4 Tabuľka najčastejších nesúladov

| IAM policy member | Authentik SAML attribute | Sedí? |
|---|---|---|
| `user:saml:admin@example.com` | `akadmin@example.com` | ❌ iný email |
| `user:saml:akadmin@example.com` | `akadmin@example.com` | ✅ |
| `team:saml:admins` | `authentik Admins` | ❌ iný názov |
| `team:saml:authentik Admins` | `authentik Admins` | ✅ |

---

## 5. Trvalé riešenie (prežitie reštartu kontajnera)

### 5.1 Kompletný startup skript

Vytvor `/etc/chef-automate/dex/start-saml-dex.sh`.  
**Poznámka:** `<CERT_CONTENT>` nahraď výstupom z [kroku 2.3](#23-extrakcia-saml-certifikátu).

```bash
docker exec chef-automate bash -c 'cat > /etc/chef-automate/dex/start-saml-dex.sh << '\''SCRIPTEOF'\''
#!/bin/bash
# Chef Automate SAML Dex startup script v2.0
set -e

CERT_FILE="/etc/chef-automate/dex/saml-ca.pem"
CONFIG_FILE="/hab/svc/automate-dex/var/etc/config.yml"
DEX_BIN="/hab/pkgs/chef/automate-dex/0.1.0/20260604110710/bin/dex"
LOG_FILE="/tmp/dex-manual.log"

echo "[dex-saml] Setting up SAML Dex..."

# Stop hab-managed Dex
hab svc stop chef/automate-dex 2>/dev/null || true
sleep 2
pkill -9 dex 2>/dev/null || true
sleep 1

# Write SAML certificate if missing/empty
if [ ! -f "$CERT_FILE" ] || [ $(wc -c < "$CERT_FILE") -lt 100 ]; then
    echo "[dex-saml] Writing SAML certificate..."
    cat > "$CERT_FILE" << '\''CERTEOF'\''
<CERT_CONTENT>
CERTEOF
    chmod 644 "$CERT_FILE"
fi

# Write config (replace with immutable)
chattr -i "$CONFIG_FILE" 2>/dev/null || true
cat > "$CONFIG_FILE" << '\''YAMLEOF'\''
issuer: https://chef.46.4.123.8.nip.io/dex
enablePasswordDB: true
storage:
  type: postgres
  config:
    host: 127.0.0.1
    port: 10145
    database: dex
    user: dex
    ssl:
      mode: verify-ca
      certFile: /hab/svc/automate-dex/config/service.crt
      keyFile: /hab/svc/automate-dex/config/service.key
      caFile: /hab/svc/automate-dex/config/root_ca.crt
web:
  https: 127.0.0.1:10117
  tlsCert: /hab/svc/automate-dex/config/service.crt
  tlsKey: /hab/svc/automate-dex/config/service.key
grpc:
  addr: 127.0.0.1:10116
  tlsCert: /hab/svc/automate-dex/config/service.crt
  tlsKey: /hab/svc/automate-dex/config/service.key
  tlsClientCA: /hab/svc/automate-dex/config/root_ca.crt
staticClients:
  - id: automate-api
    name: Automate API
    public: true
  - id: automate-session
    secret: secretchangeme
    redirectURIs:
      - /signin
    name: Automate Session Service
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
oauth2:
  responseTypes: [code, token, id_token]
  skipApprovalScreen: true
  alwaysShowLoginScreen: false
expiry:
  signingKeys: 6h
  idTokens: 3m
invalidLoginAttempts:
  enableInvalidLoginAttempts: true
  blockedDurationInMinutes: 30
  maxInvalidLoginAttemptsAllowed: 5
frontend:
  dir: /hab/pkgs/chef/automate-dex/0.1.0/20260604110710/web
  issuer: Chef Automate
  theme: chef
  extra:
    showDisclosure: false
    disclosureMessage: ""
    showBanner: false
    bannerMessage: ""
    bannerBackgroundColor: "#3864f2"
    bannerTextColor: "#FFFFFF"
YAMLEOF
chattr +i "$CONFIG_FILE"

# Start Dex
echo "[dex-saml] Starting Dex..."
nohup "$DEX_BIN" serve "$CONFIG_FILE" > "$LOG_FILE" 2>&1 &
DEX_PID=$!
sleep 5

if kill -0 $DEX_PID 2>/dev/null; then
    echo "[dex-saml] Dex OK (PID: $DEX_PID)"
    grep "listening" "$LOG_FILE" | tail -2
else
    echo "[dex-saml] FAILED!"
    cat "$LOG_FILE"
    exit 1
fi
SCRIPTEOF
chmod +x /etc/chef-automate/dex/start-saml-dex.sh'
```

### 5.2 Systemd service

```bash
docker exec chef-automate bash -c 'cat > /etc/systemd/system/dex-saml.service << '\''EOF'\''
[Unit]
Description=Chef Automate Dex with SAML connector
After=network.target

[Service]
Type=forking
ExecStart=/etc/chef-automate/dex/start-saml-dex.sh
Restart=on-failure
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF'
systemctl daemon-reload
systemctl enable dex-saml
```

---

## 6. Rýchly troubleshooting

### "Requested resource does not exist" (400)
→ Dex nemá SAML connector v config.yml. Skontroluj `grep connectors /hab/svc/automate-dex/var/etc/config.yml`

### "Invalid Auth Request ID"
→ SAML connector existuje, ale chýba OAuth2 auth request. Choď cez hlavnú stránku, nie priamo `/dex/auth/saml`.

### "no attribute with name email"
→ Zlé mapovanie atribútov. Authentik posiela URI formát (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress`), nie krátke názvy (`email`).

### "no certificates found in ca data"
→ Prázdny/nedostupný certifikát. Skontroluj `wc -c /etc/chef-automate/dex/saml-ca.pem` (musí byť ~1900B).

### "Permission Denied" pri update policy
→ Politika `administrator-access` má DENY na vlastný update. Vytvor NOVÚ politiku, needituj existujúcu.

### "It looks like you do not have permission"
→ IAM politika nesedí na SAML identifikátory. Postupuj podľa sekcie 4.

### Po reštarte kontajnera Dex nebeží
→ Spusti systemd service: `systemctl start dex-saml`

---

## 7. Užitočné príkazy

```bash
# Dex status
docker exec chef-automate ps aux | grep "dex serve"
docker exec chef-automate tail -20 /tmp/dex-manual.log

# IAM politiky
TOKEN=$(docker exec chef-automate chef-automate iam token create tmp --admin 2>&1 | tail -1)
docker exec chef-automate curl -sk -H "api-token: $TOKEN" https://localhost/apis/iam/v2/policies | python3 -m json.tool

# Authentik SAML provider
kubectl exec -n authentik deploy/authentik-server -- ak shell -c "
from authentik.providers.saml.models import SAMLProvider
sp = SAMLProvider.objects.get(name='chef-automate')
print(f'ACS: {sp.acs_url}\nIssuer: {sp.issuer}\nCert: {sp.signing_kp.name}')
"
```

---

## 8. Lessons Learned (2 dni debugovania)

1. **Habitat Supervisor prepisuje súbory** — všetky configy musia byť immutable (`chattr +i`) alebo mimo hab adresára
2. **Atribúty SAML sú v URI formáte** — Authentik default mappings používajú `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress`, nie `email`
3. **IAM politiky robia exact match** — `user:saml:akadmin@example.com` sa nerovná `user:saml:admin@example.com`
4. **Názvy skupín sú case-sensitive** — `authentik Admins` ≠ `admins`
5. **Administrator policy je chránená** — nemožno ju updatovať, treba vytvoriť novú
6. **Dex musí bežať manuálne** — hab-managed Dex ignoruje custom connectors
