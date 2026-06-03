# Restore Point - Web Flux Smoke Guardrail

Date: 2026-06-03T22:31:58+02:00

## Purpose

Add a single smoke-test guardrail to prevent fixing one web app while breaking another during Flux reconciliations.

## Script

```text
scripts/ops/web-flux-smoke-test.sh
```

## What it checks

- Flux Kustomizations READY state
- Flux HelmReleases snapshot
- Ingress host/path collisions
- Authentik redirect on JSON/API endpoints
- Known web endpoints:
  - Qdrant
  - Grafana
  - Headlamp
  - Litmus
  - Gitea
  - MLflow
  - Jenkins
  - AWX
  - VictoriaMetrics

## Initial run

```text
docs/diagnostics/web-flux-smoke-guardrail-20260603-223157/runtime
```

Exit code:

```text
2
```
