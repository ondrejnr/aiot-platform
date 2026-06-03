# Restore Point - Qdrant Dashboard Ingress Redirect

Date: 2026-06-03T14:03:09+02:00

## Purpose

Persist Qdrant root redirect into GitOps so Flux/Helm reconciliation does not remove the live fix.

## Expected behavior

- https://qdrant.46.4.123.8.nip.io/ redirects to https://qdrant.46.4.123.8.nip.io/dashboard
- https://qdrant.46.4.123.8.nip.io/dashboard remains protected by Authentik
- Authentik Qdrant application launch URL points to /dashboard

## Required Ingress annotations

```yaml
nginx.ingress.kubernetes.io/configuration-snippet: |-
  if ($request_uri = "/") {
    return 302 https://$host/dashboard;
  }
nginx.ingress.kubernetes.io/ssl-redirect: "true"
```

## Manual live restore command

```bash
kubectl -n qdrant annotate ingress qdrant \
  nginx.ingress.kubernetes.io/configuration-snippet='if ($request_uri = "/") {
  return 302 https://$host/dashboard;
}' \
  nginx.ingress.kubernetes.io/ssl-redirect='true' \
  --overwrite
```

## Authentik app launch URL repair

```bash
AUTH_POD=$(kubectl -n authentik get pods -l app.kubernetes.io/component=server -o jsonpath='{.items[0].metadata.name}')
kubectl -n authentik exec "$AUTH_POD" -- ak shell -c '
from authentik.core.models import Application
from authentik.providers.proxy.models import ProxyProvider

app = Application.objects.get(slug="qdrant")
provider = ProxyProvider.objects.get(name="qdrant")

app.name = "Qdrant"
app.meta_launch_url = "https://qdrant.46.4.123.8.nip.io/dashboard"
app.provider = provider
app.save()

print("APP", app.name, app.slug, app.meta_launch_url, app.provider)
'
```
