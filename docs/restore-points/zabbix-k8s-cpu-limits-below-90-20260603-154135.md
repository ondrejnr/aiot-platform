# Restore Point - Zabbix Kubernetes CPU Limits Below 90 Percent

Date: 2026-06-03T15:44:24+02:00

## Purpose

Lower Kubernetes CPU limits below Zabbix 90% allocatable threshold.

## Additional tuning

- aiot-emqx CPU limit: 700m
- aiot-redpanda CPU limit: 700m
- ollama CPU limit: 1000m
- alloy CPU limit: 250m

## Reason

Zabbix also alerts on CPU limits greater than 90% of node allocatable CPU, not only greater than 100%.
