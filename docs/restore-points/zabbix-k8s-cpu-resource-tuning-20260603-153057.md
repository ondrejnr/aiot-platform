# Restore Point - Zabbix Kubernetes CPU Requests/Limits Alerts

Date: 2026-06-03T15:30:57+02:00

## Purpose

Persist Kubernetes CPU request/limit tuning into GitOps so Zabbix alerts do not return after Flux/Helm reconciliation.

## Alert thresholds

- CPU requests must stay <= 50% of node allocatable CPU.
- CPU limits must stay <= 100% of node allocatable CPU.

## Main tuned areas

- Flux controllers CPU limits reduced from 1000m to 300m.
- AIOT high-replica workloads tuned to lower CPU requests/limits.
- Terrakube oversized CPU limits reduced.
- Ollama, Jenkins, MLflow, Loki, Alloy, NFS and VictoriaMetrics limits tuned where applicable.

## Emergency live fix for Flux controllers

```bash
kubectl -n flux-system set resources deployment/helm-controller -c manager --requests=cpu=50m --limits=cpu=300m
kubectl -n flux-system set resources deployment/kustomize-controller -c manager --requests=cpu=50m --limits=cpu=300m
kubectl -n flux-system set resources deployment/notification-controller -c manager --requests=cpu=50m --limits=cpu=300m
kubectl -n flux-system set resources deployment/source-controller -c manager --requests=cpu=50m --limits=cpu=300m
```

## Backup directories

```text
drwxr-xr-x. 2 root root 4096 Jun  3 15:20 /root/zbx-k8s-cpu-final-node2-20260603-152003
drwxr-xr-x. 2 root root 4096 Jun  3 14:42 /root/zbx-k8s-cpu-fix-20260603-144225
drwxr-xr-x. 2 root root 4096 Jun  3 15:08 /root/zbx-k8s-cpu-fix-followup-20260603-150843
```
