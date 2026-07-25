# Habitat Builder + Chef Automate SSO Integration

> **Účel:** Preklik z Chef Automate (Applications → Habitat Builder) do lokálneho Habitat Builderu s Authentik SSO cez Chef Dex.
> **Dátum:** 2025-07-25
> **Trvanie debugovania:** 2 dni → 5-minútová oprava podľa tohto návodu
> **IP/DNS:** `46.4.123.8`, domény `*.46.4.123.8.nip.io`

---

## Architektúra – kompletný SSO flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Prehliadač                                                       │
│ 1. Klik na "Habitat Builder" v Chef Automate sidebar            │
└┬────────────────────────────────────────────────────────────────┘
 │
 │  staticAutomateConfig.products.includes("builder") ?
 │  YES → /bldr    NO → https://bldr.habitat.sh (SaaS fallback!)
 │
 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Chef Automate load-balancer nginx (Docker: chef-automate)        │
│ location ~ ^/bldr(/.*)?$ { return 302 Chef Dex; }               │
└┬────────────────────────────────────────────────────────────────┘
 │
 │  302 → https://chef.46.4.123.8.nip.io/dex/auth
 │  ?client_id=habitat-proxy
 │  &redirect_uri=https://habitat.46.4.123.8.nip.io/oauth2/callback
 │  &response_type=code&scope=openid+profile+email
 │
 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Chef interný Dex (Docker: chef-automate, /dex)                   │
│ - habitat-proxy client: redirectURIs=.../oauth2/callback        │
│ - SAML connector → Authentik                                    │
│ - alwaysShowLoginScreen: true (nedá sa zmeniť)                  │
└┬────────────────────────────────────────────────────────────────┘
 │  SAML POST
 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Authentik (K8s: authentik namespace)                             │
│ - SAML provider: "chef-automate" (pre Chef prihlásenie)         │
│ - OAuth2 provider: "habitat-proxy" (pre Habitat Builder)        │
│   client_id=habitat-proxy                                       │
│   redirect_uris:                                                │
│     https://habitat.46.4.123.8.nip.io/oauth2/callback           │
│     https://dex.46.4.123.8.nip.io/callback                      │
└┬────────────────────────────────────────────────────────────────┘
 │  Auth dokončený → redirect na habitat.../oauth2/callback?code=...
 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Habitat Builder API Proxy nginx (Ubuntu host: hab svc)           │
│ Port 8082, /oauth2/callback → vymení code za token              │
└┬────────────────────────────────────────────────────────────────┘
 │  Token poslaný do Builder API
 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Habitat Builder API (Ubuntu host: /hab/pkgs/habitat/builder-api) │
│ provider=chef-automate (natívny Rust modul: oauth_client::a2)    │
│ token_url → https://chef.../dex/token                           │
│ userinfo_url → http://127.0.0.1:9637/userinfo (bridge)          │
│ ┌──────────────────────────────────────────────────────────┐    │
│ │ userinfo bridge (Python, port 9637)                       │    │
│ │ Volá /dex/userinfo → doplní preferred_username claim      │    │
│ │ (Builder API vyžaduje preferred_username v odpovedi!)     │    │
│ └──────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Všetky komponenty a ich konfigurácia

### 1. Habitat Builder API (`/hab/svc/builder-api/config/config.toml`)

```toml
provider = "chef-automate"                    # Natívny Rust modul, NIE "oidc"!
token_url = "https://chef.46.4.123.8.nip.io/dex/token"
userinfo_url = "http://127.0.0.1:9637/userinfo"  # Bridge, pozri nižšie
redirect_url = "https://habitat.46.4.123.8.nip.io/oauth2/callback"
client_id = "habitat-proxy"
client_secret = "habitat-proxy-secret"
authorize_url = "https://chef.46.4.123.8.nip.io/dex/auth"
```

**Dôležité:**
- Binárka podporuje len: `github`, `okta`, `chef-automate`, `azure-ad`, `active-directory`, `bitbucket`, `gitlab`
- `oidc` (generické) **nie je podporované** — musí byť `chef-automate`
- `client_secret` je povinný parameter, ale Chef Dex ho nevyžaduje (public client)

### 2. Habitat Builder API Proxy (`/hab/svc/builder-api-proxy/config/`)

**`habitat.conf.js`** – JavaScript config pre frontend:
```js
oauth_provider: "chef-automate",
oauth_authorize_url: "https://chef.46.4.123.8.nip.io/dex/auth",
oauth_client_id: "habitat-proxy",
oauth_redirect_url: "https://habitat.46.4.123.8.nip.io/oauth2/callback",
```

**`index.html`** – JavaScript auto-redirect (fallback pre SPA):
```js
// Ak URL neobsahuje ?code=, redirect na Dex
if (!window.location.search.includes('code=')) {
    document.cookie = 'oauthState=' + state + ';path=/';
    window.location.href = 'https://chef.../dex/auth?...&state=' + state;
}
```

**`nginx.conf`** – nginx map pre oauth redirect:
```nginx
map $args $do_oauth_redirect {
    default "yes";
    ~*code= "no";   # Ak už máme code, nerob redirect
}
# V location /:
if ($do_oauth_redirect = "yes") {
    return 302 https://chef.../dex/auth?...;
}
```

### 3. Chef interný Dex (Docker: `chef-automate`) – "chef dex"

**habitat-proxy client:**
- `client_id: habitat-proxy`
- `redirectURIs: ["https://habitat.46.4.123.8.nip.io/oauth2/callback"]`
- `alwaysShowLoginScreen: true` – **nedá sa zmeniť** (immutable šablóna v Chef Automate)

**SAML connector → Authentik:**
```toml
[dex.v1.sys.connectors.saml]
  sso_url = "https://authentik.46.4.123.8.nip.io/application/saml/chef-automate/sso/binding/post/"
  email_attr = "email"
  username_attr = "preferred_username"
  name_id_policy_format = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
```

### 4. Authentik (K8s: `authentik` namespace)

**OAuth2 Provider `habitat-proxy`:**
| Pole | Hodnota |
|---|---|
| name | habitat-proxy |
| client_id | habitat-proxy |
| redirect_uris | `https://habitat.46.4.123.8.nip.io/oauth2/callback` (STRICT), `https://dex.46.4.123.8.nip.io/callback` (STRICT) |

**SAML Provider `chef-automate`:**
- `sso_url`: `https://authentik.../application/saml/chef-automate/sso/binding/post/`
- `name_id_policy_format`: `urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress`

### 5. Userinfo Bridge (`/root/habitat-oauth-bridge/userinfo_bridge.py`)

**Prečo je potrebný:** Habitat Builder API (Rust) pri provideri `chef-automate` validuje token a volá userinfo endpoint. **Vyžaduje pole `preferred_username`** v odpovedi, ale Chef Dex toto pole neposiela. Bridge:

1. Prijme request od Builder API na porte 9637
2. Forwarduje ho na `https://chef.../dex/userinfo`
3. Do odpovede doplní `preferred_username` (z `name`, fallback: lokálna časť `email`)

```python
UPSTREAM_USERINFO = "https://chef.46.4.123.8.nip.io/dex/userinfo"
LISTEN_PORT = 9637
```

**Spustenie:**
- Manuálne: `python3 /root/habitat-oauth-bridge/userinfo_bridge.py &`
- Systemd service: `habitat-oauth-bridge.service` (enabled, ale port 9637 už obsadzuje manuálna inštancia)

**Poznámka:** Bridge je potrebný, aj keď provider je `chef-automate` (nielen `okta`). Bez neho Builder API nedostane `preferred_username` a prihlásenie zlyhá.

---

## Problém – 3 vrstvy (prečo preklik nefungoval)

### Vrstva 1: `staticAutomateConfig.products` prázdny/missing `"builder"`

Chef Automate UI JavaScript:

```js
// Z minifikovaného JS súboru (chunk-GMMFIWP7.js alebo main-UNRIOL4B.js)
var ai = window.staticAutomateConfig || {};
function li(t) { return ai.products && ai.products.includes(t); }

// Sidebar definícia tlačidla:
{
  name: "Habitat Builder",
  icon: "build",
  route: li("builder") ? "/bldr" : "https://bldr.habitat.sh",
  openInNewPage: true   // otvára v NOVOM tabe!
}
```

**Prečo `li("builder")` vracalo `false`:**
1. `index.html` inicializuje `staticAutomateConfig = {}`
2. `/automate.conf.js` volá `parseStaticAutomateConfig({"products":["automate"]})` — **chýba `"builder"`**
3. `ai.products` = `["automate"]` → `products.includes("builder")` = `false`
4. Fallback URL = `https://bldr.habitat.sh` (SaaS Habitat s **GitHub** prihlásením)

### Vrstva 2: `/bldr` bez koncového lomítka

Tlačidlo naviguje na `/bldr` (**bez** `/`), ale pôvodný nginx location:
```nginx
location /bldr/ {  # chytá IBA /bldr/ S LOMÍTKOM
    return 302 ...;
}
```

`/bldr` padlo do Angular SPA fallbacku → presmerované na Chef dashboard.

### Vrstva 3: Habitat Supervisor prepisuje súbory

- **`/hab/svc/` súbory** — Supervisor ich pri reštarte vyrenderuje nanovo zo šablóny + gossip configu
- **`index.html`** v automate-ui — prepíše sa runtime volaním `parseStaticAutomateConfig()` z `automate.conf.js`
- Jediná trvalá cesta: **`hab config apply`** (gossip protokol)

---

## Oprava (kroky)

### Krok 1: Pridať `"builder"` do `static_config.products`

```bash
docker exec chef-automate bash -c "
cat > /tmp/lb-static.toml <<'EOF'
[static_config]
products = [\"automate\", \"builder\"]
EOF
hab config apply automate-load-balancer.default \$(date +%s) /tmp/lb-static.toml
"
```

**Prečo `hab config apply`:** Konfigurácia sa uloží do Habitat gossip siete a prežije reštarty, re-rendery šablón, aj výmenu balíčkov. Priama editácia `/hab/svc/.../automate.conf.js` sa pri najbližšom reštarte stratí.

### Krok 2: Opraviť nginx location pre `/bldr`

Upraviť **šablónu** (aby fix prežil reštart) **aj** vyrenderovaný súbor (aby fix platil hneď):

```bash
docker exec chef-automate bash -c '
for f in \
  /hab/svc/automate-load-balancer/config/automate-builder-api-proxy-location.conf \
  /hab/pkgs/chef/automate-load-balancer/0.1.0/20260707102155/config/automate-builder-api-proxy-location.conf; do
cat > "$f" <<EOF
# Redirect /bldr and /bldr/... directly to Chef Dex for auth
location ~ ^/bldr(/.*)?\$ {
    return 302 https://chef.46.4.123.8.nip.io/dex/auth?client_id=habitat-proxy&redirect_uri=https://habitat.46.4.123.8.nip.io/oauth2/callback&response_type=code&scope=openid+profile+email;
}
EOF
done
'
```

**Prečo regex `~ ^/bldr(/.*)?$`:** Zachytí `/bldr`, `/bldr/`, `/bldr/čokoľvek` — prefixová zhoda (`location /bldr/`) chytá len s lomítkom.

### Krok 3: Reštartovať load balancer

```bash
docker exec chef-automate bash -c "
hab svc stop chef/automate-load-balancer && sleep 3 && hab svc start chef/automate-load-balancer
"
```

### Krok 4: Verifikácia

```bash
# 1. products obsahuje builder
curl -sk "https://chef.46.4.123.8.nip.io/automate.conf.js"
# Očakávaný výstup: parseStaticAutomateConfig({"products":["automate","builder"]})

# 2. /bldr redirectuje na Chef Dex
curl -skI "https://chef.46.4.123.8.nip.io/bldr"  | grep location
curl -skI "https://chef.46.4.123.8.nip.io/bldr/" | grep location
# Očakávaný výstup: location: https://chef.46.4.123.8.nip.io/dex/auth?client_id=habitat-proxy...

# 3. Userinfo bridge beží
curl -sk "http://127.0.0.1:9637/userinfo" -H "Authorization: Bearer test"
# Mal by vrátiť JSON (aj keď 401, hlavne že port odpovedá)

# 4. Habitat Builder API health
curl -sk "https://habitat.46.4.123.8.nip.io/v1/status"
```

---

## Kľúčové súbory

| Cesta | Hostiteľ | Účel |
|---|---|---|
| `/hab/svc/builder-api/config/config.toml` | Ubuntu | Habitat Builder API: provider, Dex URL, client_id |
| `/hab/svc/builder-api-proxy/config/habitat.conf.js` | Ubuntu | Frontend oauth config |
| `/hab/svc/builder-api-proxy/config/index.html` | Ubuntu | JS auto-redirect fallback |
| `/hab/svc/builder-api-proxy/config/nginx.conf` | Ubuntu | nginx: oauth map, SPA fallback |
| `/hab/pkgs/chef/automate-load-balancer/<ver>/config/automate.conf.js` | Docker | **Šablóna** `{{ toJson cfg.static_config }}` |
| `/hab/pkgs/chef/automate-load-balancer/<ver>/config/automate-builder-api-proxy-location.conf` | Docker | **Šablóna** nginx /bldr location |
| `/hab/pkgs/chef/automate-ui/<ver>/dist/browser/index.html` | Docker | `staticAutomateConfig = {}` inicializácia |
| `/hab/svc/automate-load-balancer/config/automate.conf.js` | Docker | Vyrenderovaný → `/automate.conf.js` |
| `/hab/svc/automate-load-balancer/config/automate-builder-api-proxy-location.conf` | Docker | Vyrenderovaný → nginx include |
| `/root/habitat-oauth-bridge/userinfo_bridge.py` | Ubuntu | Doplní `preferred_username` |
| `hab config apply` (gossip) | Docker | **Jediný trvalý zdroj** `static_config.products` |

---

## Debug checklist (keď to nabudúce nefunguje)

1. **`curl -sk "https://chef.../automate.conf.js"`** – obsahuje `"builder"`?
2. **`curl -skI "https://chef.../bldr"`** – vracia 302 na Dex, alebo 200 (SPA fallback)?
3. **F12 Console v prehliadači:** `window.staticAutomateConfig` – čo vracia?
4. **F12 Network tab:** Kam ide request po kliknutí na tlačidlo?
5. **Chef Dex:** `curl -sk "https://chef.../dex/.well-known/openid-configuration"` – beží?
6. **Bridge:** `ss -tlnp | grep 9637` – počúva?
7. **Habitat Builder API:** `curl -sk "https://habitat.../v1/status"` – odpovedá?
8. **Authentik OAuth2 provider:** redirect_uris obsahuje `https://habitat.../oauth2/callback`?
9. **Cache:** `Ctrl+Shift+R` v prehliadači (index.html má etag, automate.conf.js má `no-cache` ale pre istotu)

---

## Dôležité lekcie

1. **Nikdy needitovať súbory v `/hab/svc/` priamo** – Supervisor ich prepíše pri reštarte
2. **`hab config apply`** je jediná trvalá cesta pre konfiguráciu Habitat služieb
3. **nginx location:** `/bldr` ≠ `/bldr/` – prefixová zhoda nechytá bez lomítka
4. **Dva Dexy:** `dex.46.4.123.8.nip.io` (K8s, samostatný) ≠ `chef.../dex` (Docker, Chef interný) – Habitat Builder musí ísť cez **Chef interný** Dex kvôli session sharingu
5. **Provider `chef-automate`** nie `oidc` – binárka nepodporuje generické OIDC
6. **Userinfo bridge je POVINNÝ** – aj s providerom `chef-automate`, Builder API vyžaduje `preferred_username`
7. **`alwaysShowLoginScreen: true`** na Chef Dex sa nedá zmeniť – immutable šablóna
8. **`openInNewPage: true`** – tlačidlo otvára nový tab, watchovať Network v správnom tabe
9. **Debugovať JS:** `window.staticAutomateConfig` v console prezradí, čo sa reálne načíta
