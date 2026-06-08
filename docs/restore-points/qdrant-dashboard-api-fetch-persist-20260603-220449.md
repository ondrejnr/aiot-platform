# Restore Point - Qdrant Dashboard API Fetch Persist

Date: 2026-06-03T22:04:49+02:00

## Issue

Qdrant dashboard showed:

```text
Collections - Failed to fetch
```

## Root cause

External `/collections` was redirected to Authentik instead of Qdrant API.

## Working live result

```text
https://qdrant.46.4.123.8.nip.io/collections
```

returns JSON with `sensor_history`.

## Persisted GitOps fix

- `/` routes to qdrant service port 6333
- `/outpost.goauthentik.io` routes to authentik outpost only
- main qdrant ingress has `nginx.ingress.kubernetes.io/enable-global-auth: "false"`

## Diagnostics

```text
docs/diagnostics/qdrant-dashboard-api-fetch-persist-20260603-220449
```
