# Loki / Alloy / Grafana Recovery Diagnostics

Date: 2026-06-03T20:39:05+02:00

## Confirmed Symptoms

- Grafana dashboards initially returned nginx 404 for Prometheus datasource.
- Loki Explore initially showed no fresh logs.
- Direct Loki label queries worked, but fresh marker logs were not ingested.
- Node Exporter later recovered after Grafana datasource repair.
- Loki fresh ingest recovered after switching to Alloy local.file_match based container log collection.

## Confirmed Root Cause

The original Alloy pod log source was not reliably ingesting new Kubernetes pod logs.

Broken/unstable path pattern:

```text
/var/log/pods/...
/var/log/containers/<pod>_<namespace>_<container>-*.log via per-pod relabel target
```

Working pattern:

```hcl
local.file_match "container_logs_glob" {
  path_targets = [
    {
      __path__ = "/var/log/containers/*.log",
      source   = "alloy",
      job      = "kubernetes/containers-glob",
    },
  ]
}

loki.source.file "container_logs_glob" {
  targets    = local.file_match.container_logs_glob.targets
  forward_to = [loki.process.container_logs_glob.receiver]
}
```

## Verification

Fresh marker test succeeded with stream labels:

```text
source="alloy"
job="kubernetes/containers-glob"
filename="/var/log/containers/..."
```

Grafana Explore now shows logs with:

```logql
{source="alloy"}
```

## Remaining Work

Persist live working config into GitOps/Flux.
