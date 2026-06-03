# Restore Point - Loki / Alloy / Grafana Recovery

Date: 2026-06-03T20:39:05+02:00

## Summary

Recovered Grafana dashboards and Loki log ingestion.

## Fixed Issues

1. Grafana datasource drift:
   - Added/restored `Prometheus` datasource alias.
   - Added/restored `VictoriaMetrics` datasource.
   - Added/restored `Loki` datasource.

2. Loki fresh ingest failure:
   - Direct Loki labels existed.
   - Old logs existed.
   - Fresh pod logs were not ingested.
   - Alloy could see log files on disk, but old pod log source was not ingesting fresh logs.
   - Working fix is `local.file_match` over `/var/log/containers/*.log`.

## Working LogQL

```logql
{source="alloy"}
```

## Working Alloy Components

```hcl
local.file_match "container_logs_glob"
loki.source.file "container_logs_glob"
loki.process "container_logs_glob"
```

## Verification

Fresh marker was found in Loki:

```text
LOKI_LOCALMATCH_TEST_20260603_192523
```

## Diagnostics

Diagnostics saved in:

```text
docs/diagnostics/loki-alloy-grafana-recovery-20260603-203903
```

## Flux Manifests

Persisted in:

```text
flux/clusters/hetzner-new/apps/loki-alloy-grafana-recovery
```
