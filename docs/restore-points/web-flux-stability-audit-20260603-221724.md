# Restore Point - Web / Flux Stability Audit

Date: 2026-06-03T22:17:44+02:00

## Reason

Repeated web fixes caused regressions after Flux reconciliations. This audit captures Flux state, Ingress routing, Authentik redirects, host/path collisions, and web endpoint health.

## Diagnostics

```text
docs/diagnostics/web-flux-stability-audit-20260603-221724
```

## Key files

- web-checks.tsv
- ingress-routes.tsv
- ingress-collisions.tsv
- ingress-auth-annotations.txt
- flux-kustomizations-after-sync.txt
- qdrant-collections-after-flux.txt

## Principle

No more ad-hoc live-only web fixes. Each ingress/auth change must be persisted in the correct GitOps source and then verified after Flux reconcile.
