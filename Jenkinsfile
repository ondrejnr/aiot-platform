pipeline {
  agent { label 'built-in' }
  options { timestamps(); disableConcurrentBuilds(); buildDiscarder(logRotator(numToKeepStr: '20')) }
  environment { KUBECTL_VERSION='v1.30.10'; KUBECTL_BIN='/tmp/kubectl'; SNAPSHOT_DIR='snapshot' }
  stages {
    stage('Checkout') { steps { checkout scm } }
    stage('Install kubectl') { steps { sh '''
      set -eux
      rm -f "${KUBECTL_BIN}"
      curl -L -o "${KUBECTL_BIN}" "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
      chmod +x "${KUBECTL_BIN}"
      "${KUBECTL_BIN}" version --client
    ''' } }
    stage('Prepare workspace') { steps { sh '''
      set -eux
      rm -rf "${SNAPSHOT_DIR}"
      mkdir -p "${SNAPSHOT_DIR}"/{meta,cluster,rbac,storage,network,workloads,nodes,events,security,errors}
    ''' } }
    stage('Fingerprint') { steps { sh '''
      set +e
      err="${SNAPSHOT_DIR}/errors/command-errors.log"; : > "$err"
      y(){ o="$1"; shift; "$@" -o yaml > "$o" 2>>"$err" || true; }
      j(){ o="$1"; shift; "$@" -o json > "$o" 2>>"$err" || true; }
      t(){ o="$1"; shift; "$@" > "$o" 2>>"$err" || true; }

      t "${SNAPSHOT_DIR}/meta/cluster-info.txt" "${KUBECTL_BIN}" cluster-info
      t "${SNAPSHOT_DIR}/meta/api-resources.txt" "${KUBECTL_BIN}" api-resources
      t "${SNAPSHOT_DIR}/meta/api-versions.txt" "${KUBECTL_BIN}" api-versions

      y "${SNAPSHOT_DIR}/cluster/namespaces.yaml" "${KUBECTL_BIN}" get namespaces
      y "${SNAPSHOT_DIR}/cluster/customresourcedefinitions.yaml" "${KUBECTL_BIN}" get customresourcedefinitions.apiextensions.k8s.io
      y "${SNAPSHOT_DIR}/cluster/priorityclasses.yaml" "${KUBECTL_BIN}" get priorityclasses.scheduling.k8s.io

      y "${SNAPSHOT_DIR}/nodes/nodes.yaml" "${KUBECTL_BIN}" get nodes
      t "${SNAPSHOT_DIR}/nodes/nodes-wide.txt" "${KUBECTL_BIN}" get nodes -o wide
      t "${SNAPSHOT_DIR}/nodes/nodes-describe.txt" "${KUBECTL_BIN}" describe nodes
      j "${SNAPSHOT_DIR}/nodes/pods.json" "${KUBECTL_BIN}" get pods -A

      y "${SNAPSHOT_DIR}/workloads/pods.yaml" "${KUBECTL_BIN}" get pods -A
      t "${SNAPSHOT_DIR}/workloads/pods-wide.txt" "${KUBECTL_BIN}" get pods -A -o wide
      y "${SNAPSHOT_DIR}/workloads/deployments.yaml" "${KUBECTL_BIN}" get deployments.apps -A
      y "${SNAPSHOT_DIR}/workloads/statefulsets.yaml" "${KUBECTL_BIN}" get statefulsets.apps -A
      y "${SNAPSHOT_DIR}/workloads/daemonsets.yaml" "${KUBECTL_BIN}" get daemonsets.apps -A
      y "${SNAPSHOT_DIR}/workloads/replicasets.yaml" "${KUBECTL_BIN}" get replicasets.apps -A
      y "${SNAPSHOT_DIR}/workloads/jobs.yaml" "${KUBECTL_BIN}" get jobs.batch -A
      y "${SNAPSHOT_DIR}/workloads/cronjobs.yaml" "${KUBECTL_BIN}" get cronjobs.batch -A
      y "${SNAPSHOT_DIR}/workloads/serviceaccounts.yaml" "${KUBECTL_BIN}" get serviceaccounts -A
      y "${SNAPSHOT_DIR}/workloads/configmaps.yaml" "${KUBECTL_BIN}" get configmaps -A
      y "${SNAPSHOT_DIR}/workloads/poddisruptionbudgets.yaml" "${KUBECTL_BIN}" get poddisruptionbudgets.policy -A
      y "${SNAPSHOT_DIR}/workloads/resourcequotas.yaml" "${KUBECTL_BIN}" get resourcequotas -A
      y "${SNAPSHOT_DIR}/workloads/limitranges.yaml" "${KUBECTL_BIN}" get limitranges -A

      y "${SNAPSHOT_DIR}/network/services.yaml" "${KUBECTL_BIN}" get services -A
      y "${SNAPSHOT_DIR}/network/endpoints.yaml" "${KUBECTL_BIN}" get endpoints -A
      y "${SNAPSHOT_DIR}/network/endpointslices.yaml" "${KUBECTL_BIN}" get endpointslices.discovery.k8s.io -A
      y "${SNAPSHOT_DIR}/network/ingresses.yaml" "${KUBECTL_BIN}" get ingresses.networking.k8s.io -A
      y "${SNAPSHOT_DIR}/network/networkpolicies.yaml" "${KUBECTL_BIN}" get networkpolicies.networking.k8s.io -A

      y "${SNAPSHOT_DIR}/storage/persistentvolumeclaims.yaml" "${KUBECTL_BIN}" get persistentvolumeclaims -A
      y "${SNAPSHOT_DIR}/storage/persistentvolumes.yaml" "${KUBECTL_BIN}" get persistentvolumes
      y "${SNAPSHOT_DIR}/storage/storageclasses.yaml" "${KUBECTL_BIN}" get storageclasses.storage.k8s.io
      y "${SNAPSHOT_DIR}/storage/volumeattachments.yaml" "${KUBECTL_BIN}" get volumeattachments.storage.k8s.io

      y "${SNAPSHOT_DIR}/rbac/roles.yaml" "${KUBECTL_BIN}" get roles.rbac.authorization.k8s.io -A
      y "${SNAPSHOT_DIR}/rbac/rolebindings.yaml" "${KUBECTL_BIN}" get rolebindings.rbac.authorization.k8s.io -A
      y "${SNAPSHOT_DIR}/rbac/clusterroles.yaml" "${KUBECTL_BIN}" get clusterroles.rbac.authorization.k8s.io
      y "${SNAPSHOT_DIR}/rbac/clusterrolebindings.yaml" "${KUBECTL_BIN}" get clusterrolebindings.rbac.authorization.k8s.io

      y "${SNAPSHOT_DIR}/events/events.yaml" "${KUBECTL_BIN}" get events -A
      t "${SNAPSHOT_DIR}/events/events-sort-by-time.txt" "${KUBECTL_BIN}" get events -A --sort-by=.lastTimestamp

      j "${SNAPSHOT_DIR}/security/secrets-raw.json" "${KUBECTL_BIN}" get secrets -A

      python3 - <<'PY'
import json, os, collections
base="snapshot"; os.makedirs(f"{base}/security", exist_ok=True); os.makedirs(f"{base}/nodes", exist_ok=True)
raw=f"{base}/security/secrets-raw.json"; out=f"{base}/security/secrets-metadata.yaml"
if os.path.exists(raw) and os.path.getsize(raw)>0:
    data=json.load(open(raw))
    with open(out,"w") as f:
        f.write("apiVersion: v1\nkind: List\nitems:\n")
        for item in data.get("items",[]):
            m=item.get("metadata",{}); anns=sorted((m.get("annotations") or {}).keys()); labels=m.get("labels") or {}
            f.write("- apiVersion: v1\n  kind: Secret\n  metadata:\n")
            f.write(f"    name: {m.get('name','')}\n    namespace: {m.get('namespace','')}\n    labels:\n")
            if labels:
                for k,v in sorted(labels.items()): f.write(f"      {k}: {v}\n")
            else: f.write("      {}\n")
            f.write("    annotationKeys:\n")
            if anns:
                for k in anns: f.write(f"    - {k}\n")
            else: f.write("    - null\n")
            f.write(f"  type: {item.get('type','')}\n")
else:
    open(out,"w").write("apiVersion: v1\nkind: List\nitems: []\n")
pods=json.load(open(f"{base}/nodes/pods.json")) if os.path.exists(f"{base}/nodes/pods.json") and os.path.getsize(f"{base}/nodes/pods.json")>0 else {"items":[]}
by_node=collections.defaultdict(list)
for p in pods.get("items",[]):
    spec=p.get("spec",{}); meta=p.get("metadata",{}); status=p.get("status",{})
    by_node[spec.get("nodeName","<unassigned>")].append((meta.get("namespace",""),meta.get("name",""),status.get("phase",""),status.get("podIP","")))
with open(f"{base}/nodes/pods-by-node.txt","w") as f:
    for node in sorted(by_node):
        f.write(f"=== {node} ({len(by_node[node])} pods) ===\n")
        for ns,name,phase,ip in sorted(by_node[node]): f.write(f"{ns}\t{name}\t{phase}\t{ip}\n")
        f.write("\n")
PY
      rm -f "${SNAPSHOT_DIR}/security/secrets-raw.json"
      find "${SNAPSHOT_DIR}" -type f | sort > "${SNAPSHOT_DIR}/meta/file-list.txt"
      exit 0
    ''' } }
    stage('Package') { steps { sh '''
      set -eux
      tar -czf cluster-snapshot.tgz "${SNAPSHOT_DIR}"
      ls -lah cluster-snapshot.tgz
    ''' } }
  }
  post { always { archiveArtifacts artifacts: 'cluster-snapshot.tgz, snapshot/**/*', allowEmptyArchive: true } }
}
