# Restore Point - Persist Zabbix CPU Limit Overcommit Fix

Date: 2026-06-03T21:14:24+02:00

## Live fix

- local-ai Deployment/ollama container ollama: cpu limit 500m
- litmus Deployment/chaos-litmus-auth-server container auth-server: cpu limit 500m
- litmus Deployment/chaos-litmus-server container graphql-server: cpu limit 500m

## Reason

Zabbix reported node CPU limits over 100 percent of allocatable CPU.

## Verified live

- k3d-agent-2-0: 75.0% OK
- k3d-agent-3-0: 70.6% OK
- k3d-aiot-hetzner-agent-3: 51.9% OK

## Diagnostics

docs/diagnostics/zabbix-cpu-limit-overcommit-persist-20260603-211423
