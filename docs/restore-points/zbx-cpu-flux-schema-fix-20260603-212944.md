# Restore Point - Zabbix CPU Limit Flux Schema Fix

Date: 2026-06-03T21:29:45+02:00

## Issue

Flux root failed because HelmRelease postRenderer patch target contained invalid field:

```text
target.resources
```

## Fix

Removed invalid target.resources and persisted CPU caps:

```text
local-ai/ollama container ollama -> 500m
litmus/chaos-litmus-auth-server container auth-server -> 500m
litmus/chaos-litmus-server container graphql-server -> 500m
```

## Goal

Keep affected Kubernetes node total CPU limits below 100% allocatable and clear Zabbix alerts.

## Diagnostics

```text
docs/diagnostics/zbx-cpu-flux-schema-fix-20260603-212944
```
