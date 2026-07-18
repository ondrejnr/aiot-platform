# Terrakube — inštalácia na nový klaster

Tento adresár (`apps/terrakube`) je **Flux overlay** nad oficiálnym
[terrakube-helm-chart](https://terrakube-io.github.io/terrakube-helm-chart)
(`terrakube` 4.6.3). Nasádza sa cez `flux/clusters/hetzner-new/apps/terrakube.yaml`.

Cieľ tohto dokumentu: **pri novom klustri stačí prejsť zoznamom nižšie a nič
nepodceňovať** — väčšina hodnôt je environment-špecific a je hardkódovaná
v `values.yaml` / `flux/.../terrakube.yaml`.

---

## 0. Prerekvizity (musia bežať PRED Terrakube)

| Komponent | Prečo | Poznámka |
|-----------|-------|----------|
| **cert-manager** + issuer `letsencrypt-prod` | TLS certifikáty pre ingressy | Názov issueru je v `values.yaml` (`cert-manager.io/cluster-issuer`). Zmeň ho, ak máš iný. |
| **ingress-nginx** | API/UI/registry/dex ingressy | `ingressClassName: nginx` |
| **CNPG (CloudNativePG) PostgreSQL** | Terrakube DB | DB host je hardkódovaný: `pg-cluster-rw.databases.svc`. Musíš mať CNPG cluster s týmto menom/namespace, alebo zmeň `databaseHostname`. |
| **Authentik** (alebo iný OIDC IdP) | Dex connector `authentik` | Musí existovať OIDC provider s `clientID: terrakube`. Viz sekcia 3. |
| **NFS storageClass** (`nfs`) | MinIO + Redis perzistencia | `storageClass: nfs` v `values.yaml`. Zmeň na svoj SC. |
| **Node-pool s labelom `role: apps`** | `nodeSelector` pre všetky komponenty | Zmeň label alebo odstráň `nodeSelector`. |

---

## 1. Domény — zoznam miest na zmenu

Všetky vyskytujú sa v **`apps/terrakube/values.yaml`** (ak nie je uvedené inak).
Nahraď `46.4.123.8.nip.io` svojou doménou (napr. `terrakube.example.com`).

| Riadok v `values.yaml` | Hodnota | Význam |
|------------------------|---------|--------|
| 10 | `terrakube.46.4.123.8.nip.io` | UI ingress domain |
| 21 | `terrakube-api.46.4.123.8.nip.io` | API ingress domain |
| 33 | `terrakube-reg.46.4.123.8.nip.io` | Registry ingress domain |
| 54 | `https://terrakube-api.46.4.123.8.nip.io/dex` | `security.dexIssuer` |
| 60 | `https://terrakube-api.46.4.123.8.nip.io/dex` | `dex.config.issuer` |
| 72 | `https://terrakube.46.4.123.8.nip.io` | Dex `staticClients[].redirectURIs` |
| 81 | `https://authentik.46.4.123.8.nip.io/application/o/terrakube/` | Dex OIDC connector `issuer` |
| 84 | `https://terrakube-api.46.4.123.8.nip.io/dex/callback` | Dex OIDC `redirectURI` |
| 119 | `terrakube-api.46.4.123.8.nip.io` | `api.env[].org.terrakube.hostname` |

> **Dôležité:** `REACT_APP_TERRAKUBE_API_URL` sa generuje automaticky z
> `ingress.api.domain` + prípona `/api/v1/` (upstream chart). **Nikdy ju
> neodstraňuj** — bez nej UI volá `organization/...` priamo na koreň API hostu
> a Settings → General vracia 404 "The requested resource could not be found."
> Táto požiadavka je teraz explicitne zakotvená v `flux/.../terrakube.yaml`
> (`spec.values.ingress.api.path: /`).

---

## 2. Databáza (CNPG PostgreSQL)

`values.yaml`:
```yaml
api:
  properties:
    databaseType: POSTGRESQL
    databaseHostname: pg-cluster-rw.databases.svc   # ← zmeň na svoj CNPG endpoint
    databaseName: terrakube
    databaseUser: terrakube
    databasePassword: Ibm5ksY6VqOoN2kHdj1MXQCcMhSh  # plaintext fallback (používa sa len ak secret chýba)
```

Heslo sa do API injektuje cez `api.env[].AppDatabasePassword` z Secretu
`terrakube-db` (kľúč `password`). Ten Secret vytvára overlay
(`templates/secrets.yaml`) — pri novom nasadení vznikne automaticky s
hodnotou z gitu. Ak chceš vlastné heslo, zmeň `templates/secrets.yaml`
(`terrakube-db.data.password`, base64).

**Pred nasadením:** vytvor CNPG cluster s DB `terrakube` a userom `terrakube`,
alebo uprav `databaseHostname`/`databaseName`/`databaseUser`.

---

## 3. Authentik (OIDC IdP) — Dex connector

Terrakube Dex sa pripája na Authentik ako OIDC connector (`type: oidc`,
`id: authentik`). Vyžaduje:

1. V Authentiku aplikáciu `terrakube` (OIDC provider) s:
   - **Client ID:** `terrakube`
   - **Redirect URI:** `https://<API_DOMAIN>/dex/callback`
   - **Scopes:** `openid profile email groups`
2. Client secret uložený v Secreti `terrakube-dex-authentik`
   (kľúč `AUTHENTIK_CLIENT_SECRET`) — vytvára ho overlay
   (`templates/secrets.yaml`, plaintext base64 v git). Zmeň ho na svoj.

Dex čaká na Authentik cez initContainer v `postRenderers`
(`flux/.../terrakube.yaml`) — URL `https://authentik.46.4.123.8.nip.io/...`
**je tam tiež hardkódovaná**, zmeň ju na svoju.

> Ak nepoužívaš Authentik, vymeň celý `dex.config.connectors` blok
> (napr. na GitHub/Google) a uprav `security.dexIssuer`.

---

## 4. Tajomstvá (vytvára overlay automaticky)

`apps/terrakube/templates/secrets.yaml` vytvára (plaintext base64 v git,
rovnaký vzor ako ostatné sekrety v repu):

| Secret | Kľúče | Použitie |
|--------|-------|----------|
| `terrakube-db` | `password` | `AppDatabasePassword` (DB) |
| `terrakube-internal` | `internalSecret`, `patSecret` | podpis PAT / interných tokenov |
| `terrakube-minio` | `root-user`, `root-password` | MinIO `existingSecret` |
| `terrakube-dex-authentik` | `AUTHENTIK_CLIENT_SECRET` | Dex OIDC connector |

Pri novom nasadení vzniknú automaticky. Ak chceš iné hodnoty, zmeň ich v
`templates/secrets.yaml` (base64).

---

## 5. Storage / scheduling

| Hodnota | Kde | Akcia pri novom klustri |
|---------|-----|--------------------------|
| `storageClass: nfs` | `minio`, `redis` | zmeň na svoj SC |
| `nodeSelector: {role: apps}` | api, executor, minio, redis, registry | zmeň label alebo odstráň |

---

## 6. Postup pri čistom nasadení

1. Priprav prerekvizity (sekcia 0): cert-manager, nginx-ingress, CNPG Postgres,
   Authentik, NFS, node-pool.
2. V `values.yaml` nahraď všetky `46.4.123.8.nip.io` → tvoja doména (sekcia 1).
3. Uprav `databaseHostname` (sekcia 2) a Dex connector / Authentik (sekcia 3).
4. (Voliteľné) zmeň tajomstvá v `templates/secrets.yaml` (sekcia 4).
5. V `flux/clusters/<tvoj>/apps/terrakube.yaml` skontroluj initContainer URL
   Authentik (sekcia 3) a `spec.values.ingress` (musí zostať `/api/v1/`).
6. `git commit && git push` → Flux nasadí.
7. Over: `kubectl exec -n terrakube <ui-pod> -- cat /usr/share/nginx/html/env-config.js`
   → `REACT_APP_TERRAKUBE_API_URL` musí končiť na `/api/v1/`.
8. Prehliadač **hard-refresh** na UI doméne, Settings → General sa načíta.

---

## 7. Známe pripady (debug históriu)

- **404 "The requested resource could not be found." na Settings → General**
  → chýbajúce `/api/v1/` v `REACT_APP_TERRAKUBE_API_URL`. Riešenie:
  prípona je teraz explicitne v `flux/.../terrakube.yaml`. Pozri commit
  `70a251a`.
- **500 "Invalid UUID string: admin-team"** → pokazený riadok v `team` tabuľke
  (meno namiesto UUID). Fix v DB: `UPDATE team SET id='<uuid>' WHERE id='admin-team';`
- **500 NPE `groups is null`** → Dex token bez `groups` claim (stará session).
  Workaround: vymazať localStorage `oidc.user:...` v prehliadači a znova prihlásiť.
