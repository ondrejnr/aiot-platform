#!/usr/bin/env python3
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TARGET_NAMESPACE = os.environ.get("TARGET_NAMESPACE", "aiot")
DATABASE_NAMESPACE = os.environ.get("DATABASE_NAMESPACE", "databases")
PORT = int(os.environ.get("PORT", "8080"))
API_SERVER = os.environ.get("KUBERNETES_SERVICE_HOST")
API_PORT = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
KUBE_API = f"https://{API_SERVER}:{API_PORT}" if API_SERVER else "https://kubernetes.default.svc"
SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
TOKEN_PATH = SA_DIR / "token"
CA_PATH = SA_DIR / "ca.crt"
STATIC_DIR = Path("/app")
TERMINAL_PHASES = {"Succeeded", "Failed", "Error"}

COMPONENTS = [
    {"id": "sensors", "title": "Sensors", "subtitle": "simulator", "namespace": TARGET_NAMESPACE, "kind": "statefulset", "name": "aiot-sensor-simulator", "selector": {"app.kubernetes.io/component": "sensor-simulator"}, "icon": "🌡️"},
    {"id": "emqx", "title": "EMQX", "subtitle": "MQTT broker", "namespace": TARGET_NAMESPACE, "kind": "statefulset", "name": "aiot-emqx", "selector": {"app.kubernetes.io/component": "emqx"}, "icon": "📡"},
    {"id": "mqtt-to-redis", "title": "mqtt-to-redis", "subtitle": "ingest bridge", "namespace": TARGET_NAMESPACE, "kind": "deployment", "name": "aiot-mqtt-to-redis", "selector": {"app.kubernetes.io/component": "mqtt-to-redis"}, "icon": "🚚"},
    {"id": "redis", "title": "Redis", "subtitle": "stream buffer", "namespace": TARGET_NAMESPACE, "kind": "deployment", "name": "aiot-redis", "selector": {"app.kubernetes.io/component": "redis"}, "icon": "🧱"},
    {"id": "redis-to-redpanda", "title": "redis-to-redpanda", "subtitle": "consumer", "namespace": TARGET_NAMESPACE, "kind": "deployment", "name": "aiot-redis-to-redpanda", "selector": {"app.kubernetes.io/component": "redis-to-redpanda"}, "icon": "🔁"},
    {"id": "redpanda", "title": "Redpanda", "subtitle": "streaming", "namespace": TARGET_NAMESPACE, "kind": "statefulset", "name": "aiot-redpanda", "selector": {"app.kubernetes.io/component": "redpanda"}, "icon": "🐼"},
    {"id": "pg-sink", "title": "pg-sink", "subtitle": "writer", "namespace": TARGET_NAMESPACE, "kind": "deployment", "name": "aiot-pg-sink", "selector": {"app.kubernetes.io/component": "pg-sink"}, "icon": "📝"},
    {"id": "postgres", "title": "PostgreSQL", "subtitle": "CNPG", "namespace": DATABASE_NAMESPACE, "kind": "pods", "name": "pg-cluster", "selector": {"cnpg.io/cluster": "pg-cluster"}, "icon": "🐘"},
]

EXPERIMENTS = [
    {"id": "prod-aiot-pg-sink-pod-delete", "label": "pg-sink pod delete", "target": "pg-sink", "fault": "pod-delete"},
    {"id": "prod-aiot-mqtt-to-redis-pod-delete", "label": "mqtt-to-redis pod delete", "target": "mqtt-to-redis", "fault": "pod-delete"},
    {"id": "prod-aiot-redis-to-redpanda-pod-delete", "label": "redis-to-redpanda pod delete", "target": "redis-to-redpanda", "fault": "pod-delete"},
]

WORKLOAD_PREFIXES = sorted(((c["name"], c["id"]) for c in COMPONENTS), key=lambda x: len(x[0]), reverse=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(value):
    if not value or not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


def human_time(value):
    return value or ""


def kube_get(path, default=None):
    if default is None:
        default = {}
    try:
        token = TOKEN_PATH.read_text().strip()
        ctx = ssl.create_default_context(cafile=str(CA_PATH))
        req = urllib.request.Request(
            KUBE_API + path,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"_error": str(exc), "items": []}


def label_selector(labels):
    return ",".join(f"{k}={v}" for k, v in labels.items())


def list_pods(namespace):
    return kube_get(f"/api/v1/namespaces/{namespace}/pods", {"items": []}).get("items", [])


def match_labels(labels, selector):
    labels = labels or {}
    return all(labels.get(k) == v for k, v in selector.items())


def container_ready(pod):
    statuses = pod.get("status", {}).get("containerStatuses") or []
    return bool(statuses) and all(s.get("ready") for s in statuses)


def restart_count(pod):
    return sum(int(s.get("restartCount", 0)) for s in (pod.get("status", {}).get("containerStatuses") or []))


def pod_summary(pod):
    meta = pod.get("metadata", {})
    status = pod.get("status", {})
    return {
        "name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "phase": status.get("phase"),
        "ready": container_ready(pod),
        "restarts": restart_count(pod),
        "node": status.get("nodeName"),
        "createdAt": meta.get("creationTimestamp"),
        "deleting": bool(meta.get("deletionTimestamp")),
    }


def workload_path(component):
    ns = component["namespace"]
    if component["kind"] == "deployment":
        return f"/apis/apps/v1/namespaces/{ns}/deployments/{component['name']}"
    if component["kind"] == "statefulset":
        return f"/apis/apps/v1/namespaces/{ns}/statefulsets/{component['name']}"
    return None


def component_from_name(name):
    if not isinstance(name, str) or not name:
        return None
    for prefix, cid in WORKLOAD_PREFIXES:
        if name.startswith(prefix):
            return cid
    for exp in EXPERIMENTS:
        if exp["target"] in name or exp["id"] in name:
            return exp["target"]
    if "pg-sink" in name:
        return "pg-sink"
    if "mqtt-to-redis" in name:
        return "mqtt-to-redis"
    if "redis-to-redpanda" in name:
        return "redis-to-redpanda"
    return None


def infer_target_from_text(text):
    if isinstance(text, dict):
        values = []
        for key in ("applabel", "appLabel", "appns", "appkind", "name"):
            if text.get(key):
                values.append(str(text.get(key)))
        text = " ".join(values)
    elif not isinstance(text, str):
        text = str(text or "")
    for exp in EXPERIMENTS:
        if exp["id"] in text or exp["target"] in text:
            return exp["target"]
    return component_from_name(text)


def workflow_base_name(name):
    return re.sub(r"-\d{10,}$", "", name or "")


def load_workflows():
    data = kube_get(f"/apis/argoproj.io/v1alpha1/namespaces/{TARGET_NAMESPACE}/workflows", {"items": []})
    items = data.get("items", [])
    workflows = []
    for wf in items:
        meta = wf.get("metadata", {})
        status = wf.get("status", {})
        name = meta.get("name", "")
        if not (name.startswith("prod-aiot-") or "pod-delete" in name):
            continue
        nodes = []
        for node in (status.get("nodes") or {}).values():
            nodes.append({
                "displayName": node.get("displayName") or node.get("name"),
                "type": node.get("type"),
                "phase": node.get("phase"),
                "message": node.get("message") or "",
                "startedAt": node.get("startedAt"),
                "finishedAt": node.get("finishedAt"),
            })
        workflows.append({
            "name": name,
            "baseName": workflow_base_name(name),
            "phase": status.get("phase") or "Unknown",
            "startedAt": status.get("startedAt") or meta.get("creationTimestamp"),
            "finishedAt": status.get("finishedAt"),
            "createdAt": meta.get("creationTimestamp"),
            "target": infer_target_from_text(name),
            "nodes": sorted(nodes, key=lambda n: parse_ts(n.get("startedAt")) or 0),
        })
    workflows.sort(key=lambda w: parse_ts(w.get("createdAt")) or 0)
    return workflows


def load_chaos_results():
    data = kube_get(f"/apis/litmuschaos.io/v1alpha1/namespaces/{TARGET_NAMESPACE}/chaosresults", {"items": []})
    results = []
    for cr in data.get("items", []):
        meta = cr.get("metadata", {})
        status = cr.get("status", {})
        exp_status = status.get("experimentStatus") or status.get("experimentstatus") or {}
        history = status.get("history") or {}
        targets = history.get("targets") or []
        target = None
        if targets:
            target = component_from_name(targets[0].get("name")) or infer_target_from_text(str(targets[0]))
        results.append({
            "name": meta.get("name"),
            "createdAt": meta.get("creationTimestamp"),
            "phase": exp_status.get("phase"),
            "verdict": exp_status.get("verdict"),
            "score": exp_status.get("probeSuccessPercentage"),
            "target": target or infer_target_from_text(meta.get("name", "")),
            "history": history,
        })
    results.sort(key=lambda r: parse_ts(r.get("createdAt")) or 0)
    return results


def load_chaos_engines():
    data = kube_get(f"/apis/litmuschaos.io/v1alpha1/namespaces/{TARGET_NAMESPACE}/chaosengines", {"items": []})
    engines = []
    for ce in data.get("items", []):
        meta = ce.get("metadata", {})
        spec = ce.get("spec", {})
        status = ce.get("status", {})
        appinfo = spec.get("appinfo") or spec.get("appInfo") or ""
        engines.append({
            "name": meta.get("name"),
            "createdAt": meta.get("creationTimestamp"),
            "engineStatus": status.get("engineStatus"),
            "target": infer_target_from_text(appinfo) or infer_target_from_text(meta.get("name", "")),
            "experiments": status.get("experiments") or [],
        })
    engines.sort(key=lambda e: parse_ts(e.get("createdAt")) or 0)
    return engines


def event_timestamp(event):
    return event.get("eventTime") or event.get("lastTimestamp") or event.get("firstTimestamp") or event.get("metadata", {}).get("creationTimestamp")


def classify_event(event):
    reason = event.get("reason") or ""
    obj = event.get("involvedObject", {})
    kind = obj.get("kind", "")
    name = obj.get("name", "")
    msg = event.get("message") or ""
    text = f"{reason} {kind} {name} {msg}"
    component = component_from_name(name) or infer_target_from_text(msg)
    icon = "•"
    level = "info"
    title = reason or kind or "Event"
    clean = msg

    if kind == "Workflow" or reason.startswith("Workflow"):
        icon = "🧪"
        component = component or infer_target_from_text(name)
        title = "Workflow"
        if "Succeeded" in reason:
            title, icon, level = "Experiment finished", "✅", "success"
        elif "Running" in reason:
            title, icon = "Experiment step running", "▶️"
    elif kind == "ChaosEngine" or reason.startswith("Chaos") or reason.startswith("Experiment") or reason in {"PreChaosCheck", "PostChaosCheck", "Summary"}:
        icon = "⚙️"
        component = component or infer_target_from_text(name)
        title = "Chaos engine"
        if reason == "ChaosInject":
            title, icon, level = "Fault injected", "💥", "danger"
        elif reason in {"Summary", "ChaosEngineCompleted"}:
            title, icon, level = "Chaos completed", "✅", "success"
    elif kind == "ChaosResult" or reason in {"Pass", "Fail", "Awaited"}:
        component = component or infer_target_from_text(name)
        if reason == "Pass":
            title, icon, level = "Result PASS", "🟢", "success"
        elif reason == "Fail":
            title, icon, level = "Result FAIL", "🔴", "danger"
        else:
            title, icon = "Result awaited", "⏳"
    elif reason == "Killing" and kind == "Pod":
        title, icon, level = "Pod deleted", "💥", "danger"
        clean = f"{name}: {msg}"
    elif reason == "SuccessfulCreate" and "Created pod:" in msg:
        title, icon, level = "Replacement pod created", "🛠️", "warn"
        component = component or component_from_name(msg.split("Created pod:", 1)[1].strip())
    elif reason in {"Created", "Started", "Pulled"} and component:
        title, icon = f"Pod {reason.lower()}", "🛠️"
        if reason == "Started":
            level = "success"

    return {
        "time": event_timestamp(event),
        "reason": reason,
        "kind": kind,
        "object": name,
        "message": clean,
        "title": title,
        "icon": icon,
        "level": level,
        "component": component,
    }


def load_story_events(component_ids):
    data = kube_get(f"/api/v1/namespaces/{TARGET_NAMESPACE}/events", {"items": []})
    raw = data.get("items", [])
    raw.sort(key=lambda e: parse_ts(event_timestamp(e)) or 0)
    story = []
    for ev in raw[-300:]:
        item = classify_event(ev)
        reason = item["reason"]
        kind = item["kind"]
        component = item.get("component")
        msg = item.get("message") or ""
        important = (
            kind in {"Workflow", "ChaosEngine", "ChaosResult"}
            or reason.startswith("Workflow")
            or reason.startswith("Chaos")
            or reason.startswith("Experiment")
            or reason in {"Killing", "SuccessfulCreate", "Pass", "Fail", "Awaited", "Summary", "PreChaosCheck", "PostChaosCheck"}
            or (component in component_ids and reason in {"Created", "Started", "Pulled"})
            or "pod-delete" in msg
        )
        if important:
            story.append(item)
    return story[-90:]


def build_components():
    pods_by_ns = {
        TARGET_NAMESPACE: list_pods(TARGET_NAMESPACE),
        DATABASE_NAMESPACE: list_pods(DATABASE_NAMESPACE) if DATABASE_NAMESPACE != TARGET_NAMESPACE else [],
    }
    output = []
    for comp in COMPONENTS:
        pods = [p for p in pods_by_ns.get(comp["namespace"], []) if match_labels(p.get("metadata", {}).get("labels"), comp["selector"])]
        pod_items = sorted([pod_summary(p) for p in pods], key=lambda p: p.get("name") or "")
        desired = len(pod_items)
        ready = sum(1 for p in pod_items if p.get("ready") and p.get("phase") == "Running")
        workload = None
        path = workload_path(comp)
        if path:
            workload = kube_get(path, {})
            if workload and not workload.get("_error"):
                spec = workload.get("spec", {})
                status = workload.get("status", {})
                desired = int(spec.get("replicas", desired) or 0)
                ready = int(status.get("readyReplicas", ready) or 0)
        degraded = desired > 0 and ready < desired
        pending = any(p.get("phase") not in {"Running", "Succeeded"} or not p.get("ready") for p in pod_items)
        health = "green"
        if degraded:
            health = "red"
        elif pending:
            health = "yellow"
        output.append({
            "id": comp["id"],
            "title": comp["title"],
            "subtitle": comp["subtitle"],
            "icon": comp["icon"],
            "namespace": comp["namespace"],
            "kind": comp["kind"],
            "name": comp["name"],
            "desired": desired,
            "ready": ready,
            "health": health,
            "pods": pod_items[:64],
        })
    return output


def build_experiment_cards(workflows, results):
    cards = []
    for exp in EXPERIMENTS:
        wf_matches = [w for w in workflows if w["baseName"] == exp["id"] or w["name"].startswith(exp["id"])]
        latest = wf_matches[-1] if wf_matches else None
        result_matches = [r for r in results if r.get("target") == exp["target"]]
        result = result_matches[-1] if result_matches else None
        cards.append({
            **exp,
            "lastWorkflow": latest,
            "lastResult": result,
            "status": latest.get("phase") if latest else "never run",
            "score": result.get("score") if result else None,
            "verdict": result.get("verdict") if result else None,
        })
    return cards


def build_impact(story, latest_workflow, latest_result):
    impact = {
        "target": latest_workflow.get("target") if latest_workflow else None,
        "deletedPod": None,
        "replacementPod": None,
        "killTime": None,
        "replacementTime": None,
        "resultTime": None,
        "recoverySeconds": None,
        "verdict": latest_result.get("verdict") if latest_result else None,
        "score": latest_result.get("score") if latest_result else None,
    }
    for ev in story:
        if ev.get("reason") == "Killing" and ev.get("kind") == "Pod":
            impact["deletedPod"] = ev.get("object")
            impact["killTime"] = ev.get("time")
            impact["target"] = ev.get("component") or impact["target"]
        if ev.get("reason") == "SuccessfulCreate" and "Created pod:" in (ev.get("message") or ""):
            pod = ev["message"].split("Created pod:", 1)[1].strip().split()[0]
            if component_from_name(pod) == impact.get("target") or not impact.get("replacementPod"):
                impact["replacementPod"] = pod
                impact["replacementTime"] = ev.get("time")
        if ev.get("reason") in {"Pass", "Fail"}:
            impact["resultTime"] = ev.get("time")
    start = parse_ts(impact.get("killTime"))
    end = parse_ts(impact.get("replacementTime")) or parse_ts(impact.get("resultTime"))
    if start and end and end >= start:
        impact["recoverySeconds"] = round(end - start)
    return impact


def build_state():
    components = build_components()
    workflows = load_workflows()
    engines = load_chaos_engines()
    results = load_chaos_results()
    active = [w for w in workflows if w.get("phase") not in TERMINAL_PHASES]
    latest_workflow = (active[-1] if active else (workflows[-1] if workflows else None))
    latest_result = results[-1] if results else None
    story = load_story_events({c["id"] for c in components})
    impact = build_impact(story, latest_workflow, latest_result)
    target = impact.get("target") or (latest_workflow.get("target") if latest_workflow else None)
    if target:
        for comp in components:
            if comp["id"] == target and latest_workflow and latest_workflow.get("phase") not in TERMINAL_PHASES and comp["health"] == "green":
                comp["health"] = "yellow"
                comp["chaosTarget"] = True
            elif comp["id"] == target:
                comp["chaosTarget"] = True
    return {
        "generatedAt": now_iso(),
        "mode": "read-only",
        "namespace": TARGET_NAMESPACE,
        "components": components,
        "workflows": workflows[-12:],
        "latestWorkflow": latest_workflow,
        "chaosEngines": engines[-8:],
        "chaosResults": results[-8:],
        "experiments": build_experiment_cards(workflows, results),
        "timeline": story,
        "impact": impact,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AIoTChaosTheater/0.1"

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))
        sys.stdout.flush()

    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":
            self.send_bytes(b"ok\n", "text/plain; charset=utf-8")
            return
        if path == "/api/state":
            try:
                body = json.dumps(build_state(), ensure_ascii=False).encode("utf-8")
                self.send_bytes(body, "application/json; charset=utf-8")
            except Exception as exc:
                body = json.dumps({"error": str(exc), "generatedAt": now_iso()}).encode("utf-8")
                self.send_bytes(body, "application/json; charset=utf-8", 500)
            return
        file_map = {
            "/": "index.html",
            "/index.html": "index.html",
            "/styles.css": "styles.css",
            "/app.js": "app.js",
        }
        if path in file_map:
            target = STATIC_DIR / file_map[path]
            ctype = "text/html; charset=utf-8" if target.suffix == ".html" else "text/css; charset=utf-8" if target.suffix == ".css" else "application/javascript; charset=utf-8"
            self.send_bytes(target.read_bytes(), ctype)
            return
        self.send_bytes(b"not found\n", "text/plain; charset=utf-8", 404)


def main():
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"AIoT Chaos Theater listening on :{PORT}, namespace={TARGET_NAMESPACE}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
