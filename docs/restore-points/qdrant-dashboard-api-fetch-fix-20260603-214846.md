# Restore Point - Qdrant Dashboard Failed to Fetch Fix

Date: 2026-06-03T21:49:07+02:00

## Issue

Qdrant dashboard loaded but Collections showed:

```text
Failed to fetch
```

## Root cause

External API path `/collections` was redirected to Authentik:

```text
302 /outpost.goauthentik.io/start
```

Internal Qdrant API was healthy.

## Live fix

Split ingress paths:

- `/` -> qdrant service port 6333
- `/outpost.goauthentik.io` -> authentik outpost service

## Backup

```text
/root/qdrant-ingress-fix-20260603-214846
```
