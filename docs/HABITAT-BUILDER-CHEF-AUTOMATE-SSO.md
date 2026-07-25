# Habitat Builder + Chef Automate SSO Integration

> **Účel:** Preklik z Chef Automate (Applications → Habitat Builder) do lokálneho Habitat Builderu s Authentik SSO.
> **Dátum:** 2025-07-25
> **Trvanie riešenia:** 2 dni debugovania → 5-minútová oprava pri opakovanej inštalácii

---

## Architektúra

```
Prehliadač → Chef Automate UI (tlačidlo "Habitat Builder")
              │
              ├─ products=["automate","builder"] ? /bldr : https://bldr.habitat.sh
              │
              ▼
        nginx: location ~ ^/bldr(/.*)?$ → 302 → Chef Dex
              │
              ▼
        Chef Dex (interne v Docker kontajneri)
              │
              ├─ SAML connector → Authentik
              │
              ▼
        Habitat Builder API (habitat.46.4.123.8.nip.io)
              │
              provider=chef-automate → validuje token cez Chef Dex
```

---

## Problém (3 vrstvy)

### 1. `staticAutomateConfig.products` neobsahuje `"builder"`

Chef Automate UI JavaScript rozhoduje o URL tlačidla takto:

```js
// Z minifikovaného JS: chunk-GMMFIWP7.js
var ai = window.staticAutomateConfig || {};
function li(t) { return ai.products && ai.products.includes(t); }

// Tlačidlo Habitat Builder:
{ name: "Habitat Builder", route: li("builder") ? "/bldr" : "https://bldr.habitat.sh", openInNewPage: true }
```

Ak `products` neobsahuje `"builder"`, tlačidlo ide na **SaaS Habitat** (`bldr.habitat.sh`) s GitHub prihlásením.

**Prečo to nefungovalo:**
- `index.html` inicializuje `staticAutomateConfig = {}`
- Následne `/automate.conf.js` volá `parseStaticAutomateConfig({"products":["automate"]})`
- **Chýba `"builder"`** → `li("builder")` vracia `false` → fallback na SaaS URL

### 2. `/bldr` bez lomítka nechytá nginx

Tlačidlo naviguje na `/bldr` (**bez** koncovej `/`), ale pôvodný nginx location:

```nginx
location /bldr/ {  # chytá LEN /bldr/ s lomítkom!
    return 302 ...;
}
```

`/bldr` spadol do Angular SPA fallbacku → presmerovaný späť na Chef dashboard.

### 3. Priama editácia súborov nefunguje

- `index.html` – prepíše sa volaním `parseStaticAutomateConfig()` z `automate.conf.js`
- `/hab/svc/.../automate.conf.js` – Supervisor ho pri každom reštarte vyrenderuje nanovo zo šablóny + gossip configu
- Šablóna: `/hab/pkgs/chef/automate-load-balancer/<ver>/config/automate.conf.js` obsahuje `{{ toJson cfg.static_config }}`

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

Toto aplikuje config cez **Habitat gossip** – prežije reštarty aj re-renderovanie šablón.

### Krok 2: Opraviť nginx location pre `/bldr`

Upraviť šablónu aj vyrenderovaný súbor:

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

### Krok 3: Reštartovať load balancer

```bash
docker exec chef-automate bash -c "
hab svc stop chef/automate-load-balancer
sleep 3
hab svc start chef/automate-load-balancer
"
```

### Krok 4: Verifikácia

```bash
# 1. products obsahuje builder
curl -sk "https://chef.46.4.123.8.nip.io/automate.conf.js"
# Očakávaný výstup: parseStaticAutomateConfig({"products":["automate","builder"]})

# 2. /bldr redirectuje na Chef Dex (bez aj s lomítkom)
curl -skI "https://chef.46.4.123.8.nip.io/bldr"  | grep location
curl -skI "https://chef.46.4.123.8.nip.io/bldr/" | grep location
# Očakávaný výstup: location: https://chef.46.4.123.8.nip.io/dex/auth?client_id=habitat-proxy...
```

---

## Kľúčové súbory

| Cesta | Účel |
|---|---|
| `/hab/pkgs/chef/automate-load-balancer/<ver>/config/automate.conf.js` | **Šablóna** – `{{ toJson cfg.static_config }}` |
| `/hab/pkgs/chef/automate-load-balancer/<ver>/config/automate-builder-api-proxy-location.conf` | **Šablóna** – nginx location pre /bldr |
| `/hab/pkgs/chef/automate-ui/<ver>/dist/browser/index.html` | Inicializuje `staticAutomateConfig = {}` |
| `/hab/svc/automate-load-balancer/config/automate.conf.js` | Vyrenderovaný súbor → servíruje sa ako `/automate.conf.js` |
| Habitat gossip (`hab config apply`) | **Jediný trvalý zdroj** `static_config.products` |

---

## Dôležité lekcie

1. **Nikdy needitovať súbory v `/hab/svc/` priamo** – Supervisor ich prepíše pri reštarte
2. **`hab config apply`** je jediná trvalá cesta pre konfiguráciu Habitat služieb
3. **nginx location presná zhoda:** `/bldr` ≠ `/bldr/` – používať regex `~ ^/bldr(/.*)?$`
4. **Debugovať JavaScript v prehliadači:** `staticAutomateConfig` v konzole prezradí, čo sa reálne načíta
5. **Cache:** `automate.conf.js` má `cache-control: private, no-cache, no-store`, ale index.html má `etag` – pri zmenách treba **Ctrl+Shift+R**
