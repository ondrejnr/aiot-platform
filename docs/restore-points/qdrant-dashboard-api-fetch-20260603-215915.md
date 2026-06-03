# Restore Point - Qdrant Dashboard Failed to Fetch

Date: 2026-06-03T21:59:42+02:00

## Issue

Qdrant dashboard showed:

```text
Collections - Failed to fetch
```

## Root cause

External `/collections` request was redirected to Authentik:

```text
302 /outpost.goauthentik.io/start
```

Internal Qdrant API was healthy.

## Live fix

Removed auth redirect annotations from main Qdrant ingress and forced:

- `/` -> qdrant service port 6333
- `/outpost.goauthentik.io` -> authentik outpost only

## Backup

```text
/root/qdrant-auth-redirect-fix-20260603-215915
```
