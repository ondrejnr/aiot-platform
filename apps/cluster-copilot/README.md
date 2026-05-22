# Cluster Copilot

Remote MCP tool server for the Hetzner Kubernetes cluster.

## What it provides

- `cluster_status` for a quick cluster snapshot
- `kubectl` for arbitrary kubectl commands
- `get_pod_logs`
- `rollout_restart`
- `scale_deployment`
- `describe`
- `exec_in_pod`
- `apply_yaml`
- `delete_resource`

## Deployment

This app is deployed by Flux from `flux/clusters/hetzner-new/apps/cluster-copilot.yaml`.

The server runs with a cluster-admin service account inside the cluster and is exposed via the ingress host defined in `values.yaml`.

## Client configuration

For MCP-capable VS Code clients, the workspace config is:

```json
{
  "servers": {
    "cluster-copilot": {
      "type": "http",
      "url": "https://cluster-copilot.46.4.123.8.nip.io/mcp"
    }
  }
}
```
