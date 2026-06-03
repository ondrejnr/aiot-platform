# Zabbix CPU Limit Overcommit Recovery

Date: 2026-06-03T21:07:47+02:00

## Alert

Zabbix reported Kubernetes node CPU limit overcommit over 100% allocatable.

Affected nodes:

- k3d-agent-2-0
- k3d-aiot-hetzner-agent-3
- k3d-agent-3-0

## Live Fix Applied

- local-ai / Deployment ollama / container ollama: 1000m -> 500m
- litmus / Deployment chaos-litmus-auth-server / container auth-server: 550m -> 500m
- litmus / Deployment chaos-litmus-server / container graphql-server: 550m -> 500m

## Verification After Fix

- k3d-agent-2-0: 75.0% OK
- k3d-agent-3-0: 70.6% OK
- k3d-aiot-hetzner-agent-3: 51.9% OK

## Restore Script

Live restore script from initial repair run:

```text
/root/zabbix-cpu-limit-fix-20260603-210557/restore-cpu-limits.sh
```
