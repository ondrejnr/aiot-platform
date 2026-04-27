#!/bin/bash
set -e

# Zones:
#   control = master (no scheduling for user workloads)
#   data    = GCP workers (16GB RAM, Piraeus storage, primary zone)
#   build   = OCI workers (konflux build + edge workloads) (11GB RAM, slabšie, smie hostit stateless)
echo "=== Labelling nodes ==="
kubectl label node aiot-master      workload-zone=control --overwrite
kubectl label node aiot-worker-01   workload-zone=data    --overwrite
kubectl label node aiot-worker-02   workload-zone=data    --overwrite
kubectl label node oci-e5-node1     workload-zone=build   --overwrite
kubectl label node oci-e5-node2     workload-zone=build   --overwrite

echo "=== Verify ==="
kubectl get nodes -L workload-zone
