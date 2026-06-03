# Restore Point - Zabbix Kubernetes CPU Limit Overcommit

Date: 2026-06-03T21:07:50+02:00

## Issue

Zabbix reported CPU limit overcommit on Kubernetes nodes:

- k3d-agent-2-0
- k3d-aiot-hetzner-agent-3
- k3d-agent-3-0

## Live Remediation

CPU limits were reduced:

```text
local-ai Deployment/ollama container ollama: 1000m -> 500m
litmus Deployment/chaos-litmus-auth-server container auth-server: 550m -> 500m
litmus Deployment/chaos-litmus-server container graphql-server: 550m -> 500m
```

## Verification

After live remediation:

```text
k3d-agent-2-0                 75.0% OK
k3d-agent-3-0                 70.6% OK
k3d-aiot-hetzner-agent-3      51.9% OK
```

## Restore

Live restore script:

```bash
/root/zabbix-cpu-limit-fix-20260603-210557/restore-cpu-limits.sh
```

## Diagnostics

```text
docs/diagnostics/zabbix-node-cpu-limit-overcommit-20260603-210747
```
