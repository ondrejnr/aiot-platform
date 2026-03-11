# K8s Cluster Backup — Cerebrus AIoT Platform

Kompletný backup všetkých custom Kubernetes manifestov.
Dátum: 2026-03-11

## Štruktúra

    k8s/
    ├── aiot/          (33 súborov) — Hlavná AIoT platforma
    │   ├── ss-*.yaml           — StatefulSets (postgres, redpanda)
    │   ├── deploy-*.yaml       — Deployments
    │   ├── cm-*.yaml           — ConfigMaps
    │   ├── secret-*.yaml       — Secrets
    │   ├── cj-*.yaml           — CronJobs
    │   ├── services.yaml       — Services
    │   ├── ingress.yaml        — Ingress
    │   └── pvc.yaml            — PersistentVolumeClaims
    │
    ├── default/       (16 súborov) — LAMP, Grafana, ELK, Prometheus
    │   ���── deploy-*.yaml       — Deployments
    │   ├── ds-*.yaml           — DaemonSets (metricbeat)
    │   ├── cm-*.yaml           — ConfigMaps
    │   ├── services.yaml       — Services
    │   ├── ingress.yaml        — Ingress (grafana, kibana, lamp)
    │   └── pvc.yaml            — PVCs (elasticsearch, grafana, mysql, www)
    │
    ├── emqx/          (6 súborov) — MQTT broker cluster
    │   ├── ss-emqx.yaml        — StatefulSet
    │   ├── deploy-*.yaml       — mqtt-kafka-bridge
    │   ├── cm-*.yaml           — ConfigMaps
    │   ├── services.yaml       — Services
    │   └── ingress.yaml        — Dashboard ingress
    │
    ├── ingress-nginx/ (4 súbory) — AI Accelerator dashboard
    │   ├── deploy-*.yaml       — Deployment
    │   ├── cm-*.yaml           — ConfigMap (Flask app)
    │   ├── services.yaml       — Service
    │   └── ingress.yaml        — Ingress
    │
    ├── loadtest/      (2 súbory) — MQTT load generator
    │   ├── deploy-*.yaml       — Deployment (400 machines, 1000 msg/s)
    │   └── cm-*.yaml           — ConfigMap (loadgen.py)
    │
    └── monitoring/    (14 súborov) — InfluxDB, VictoriaMetrics, writers
        ├── deploy-*.yaml       — Deployments (7x)
        ├── cm-*.yaml           — ConfigMaps (5x)
        ├── services.yaml       — Services
        └── pvc.yaml            — PVC (influxdb)

## Komponenty

| Namespace      | Komponent            | Typ          | Repliky |
|----------------|----------------------|--------------|---------|
| aiot           | postgres             | StatefulSet  | 1       |
| aiot           | redpanda             | StatefulSet  | 1       |
| aiot           | digital-twin         | Deployment   | 1       |
| aiot           | api-gateway          | Deployment   | 1       |
| aiot           | pg-sink              | Deployment   | 1       |
| aiot           | sensor-simulator     | Deployment   | 1       |
| aiot           | qdrant               | Deployment   | 1       |
| aiot           | qdrant-indexer       | Deployment   | 1       |
| aiot           | rag-worker           | Deployment   | 1       |
| aiot           | redis-master         | Deployment   | 1       |
| aiot           | redis-pg-flusher     | Deployment   | 1       |
| aiot           | pgadmin              | Deployment   | 1       |
| aiot           | cloudbeaver          | Deployment   | 1       |
| aiot           | ngrok-proxy          | Deployment   | 1       |
| emqx           | emqx                 | StatefulSet  | 3       |
| emqx           | mqtt-kafka-bridge    | Deployment   | 3       |
| monitoring     | influxdb             | Deployment   | 1       |
| monitoring     | influxdb-proxy       | Deployment   | 1       |
| monitoring     | influx-writer        | Deployment   | 3       |
| monitoring     | victoriametrics      | Deployment   | 1       |
| monitoring     | vm-proxy             | Deployment   | 1       |
| monitoring     | vm-writer            | Deployment   | 1       |
| monitoring     | loadtest             | Deployment   | 1       |
| default        | elasticsearch        | Deployment   | 1       |
| default        | grafana              | Deployment   | 1       |
| default        | kibana               | Deployment   | 1       |
| default        | lamp-deployment      | Deployment   | 1       |
| default        | prometheus           | Deployment   | 1       |
| default        | ws-proxy             | Deployment   | 1       |
| default        | metricbeat           | DaemonSet    | all     |
| ingress-nginx  | ai-accelerator       | Deployment   | 1       |
| loadtest       | mqtt-loadgen         | Deployment   | 1       |

## Obnova

    # 1. Namespaces
    kubectl create ns aiot emqx loadtest monitoring

    # 2. Secrets a ConfigMaps najprv
    kubectl apply -f k8s/aiot/secret-*.yaml
    kubectl apply -f k8s/*/cm-*.yaml

    # 3. PVC
    kubectl apply -f k8s/*/pvc.yaml

    # 4. StatefulSets
    kubectl apply -f k8s/*/ss-*.yaml

    # 5. Deployments
    kubectl apply -f k8s/*/deploy-*.yaml

    # 6. DaemonSets
    kubectl apply -f k8s/*/ds-*.yaml

    # 7. Services
    kubectl apply -f k8s/*/services.yaml

    # 8. Ingress
    kubectl apply -f k8s/*/ingress.yaml

    # 9. CronJobs
    kubectl apply -f k8s/*/cj-*.yaml

## Externé prístupy

| URL                                      | Služba           |
|------------------------------------------|------------------|
| grafana.34.90.168.150.nip.io             | Grafana          |
| kibana.34.90.168.150.nip.io              | Kibana           |
| lamp.34.90.168.150.nip.io                | LAMP stack       |
| emqx.34.90.168.150.nip.io               | EMQX Dashboard   |
| ai-accelerator.34.90.168.150.nip.io     | AIoT Dashboard   |
| aiot-api.34.90.168.150.nip.io            | API Gateway      |
| pgadmin.34.90.168.150.nip.io             | pgAdmin          |
| cloudbeaver.34.90.168.150.nip.io         | CloudBeaver      |
| digital-twin.34.90.168.150.nip.io        | Digital Twin     |
