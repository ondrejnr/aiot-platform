# Restore Point - Web Flux Smoke Script Fix

Date: 2026-06-03T22:44:51+02:00

## Issue

Initial smoke script produced false failures:
- curl response parsing was unreliable
- Flux False count matched SUSPENDED=False, not READY=False

## Fix

Updated:

```text
scripts/ops/web-flux-smoke-test.sh
```

## Initial fixed run

```text
docs/diagnostics/web-flux-smoke-script-fix-20260603-223157/runtime
```

Smoke exit code:

```text
2
```
