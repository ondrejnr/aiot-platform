from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

INSTRUCTIONS = """

You are the Hetzner cluster operator.
You have cluster-admin access to the Kubernetes cluster through this server.
Use the tools to inspect and change the cluster when the user asks.
Prefer cluster_status for a quick overview.
Do not guess cluster state. Always use the tools.
""".strip()

mcp = FastMCP(
    "Hetzner Cluster Copilot",
    instructions=INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
)
mcp.settings.host = "0.0.0.0"
mcp.settings.port = int(os.environ.get("PORT", "8000"))


def _quote(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _run(command: list[str], *, stdin: str | None = None, timeout_seconds: int = 120) -> str:
    try:
        result = subprocess.run(
            command,
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=os.environ.copy(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return (
            f"Command timed out after {timeout_seconds}s\n"
            f"$ {_quote(command)}\n"
            f"stdout:\n{stdout.rstrip()}\n"
            f"stderr:\n{stderr.rstrip()}\n"
        ).strip() + "\n"

    parts = [f"$ {_quote(command)}", f"exit_code={result.returncode}"]
    if result.stdout:
        parts.append("stdout:")
        parts.append(result.stdout.rstrip())
    if result.stderr:
        parts.append("stderr:")
        parts.append(result.stderr.rstrip())
    return "\n".join(parts).strip() + "\n"


@mcp.tool()
def cluster_status(timeout_seconds: int = 120) -> str:
    """Get a concise cluster snapshot."""
    script = """
set -eu
printf '== Nodes ==\n'
kubectl get nodes -o wide
printf '\n== Namespaces ==\n'
kubectl get namespaces
printf '\n== Non-running pods ==\n'
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded || true
printf '\n== Services ==\n'
kubectl get services -A
printf '\n== Ingresses ==\n'
kubectl get ingress -A
printf '\n== Recent events ==\n'
kubectl get events -A --sort-by=.lastTimestamp | tail -40 || true
""".strip()
    return _run(["/bin/sh", "-lc", script], timeout_seconds=timeout_seconds)


@mcp.tool()
def kubectl(command: str, timeout_seconds: int = 120) -> str:
    """Run an arbitrary kubectl command inside the cluster-admin tool server."""
    command = command.strip()
    if not command:
        return "No kubectl command provided."
    if command.startswith("kubectl "):
        command = command[len("kubectl ") :].strip()
    return _run(["/bin/sh", "-lc", f"kubectl {command}"], timeout_seconds=timeout_seconds)


@mcp.tool()
def get_pod_logs(
    namespace: str,
    pod: str,
    container: Optional[str] = None,
    tail_lines: int = 200,
    previous: bool = False,
    timeout_seconds: int = 120,
) -> str:
    """Fetch logs for a pod."""
    command = ["kubectl", "logs", "-n", namespace, pod, "--tail", str(tail_lines)]
    if container:
        command.extend(["-c", container])
    if previous:
        command.append("--previous")
    return _run(command, timeout_seconds=timeout_seconds)


@mcp.tool()
def rollout_restart(namespace: str, deployment: str, timeout_seconds: int = 120) -> str:
    """Restart a deployment rollout."""
    return _run(["kubectl", "rollout", "restart", "deployment", deployment, "-n", namespace], timeout_seconds=timeout_seconds)


@mcp.tool()
def scale_deployment(namespace: str, deployment: str, replicas: int, timeout_seconds: int = 120) -> str:
    """Scale a deployment to the requested replica count."""
    return _run(
        ["kubectl", "scale", "deployment", deployment, "-n", namespace, "--replicas", str(replicas)],
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def describe(resource: str, name: str, namespace: Optional[str] = None, timeout_seconds: int = 120) -> str:
    """Describe a Kubernetes resource."""
    command = ["kubectl", "describe", resource, name]
    if namespace:
        command.extend(["-n", namespace])
    return _run(command, timeout_seconds=timeout_seconds)


@mcp.tool()
def exec_in_pod(
    namespace: str,
    pod: str,
    command: str,
    container: Optional[str] = None,
    timeout_seconds: int = 120,
) -> str:
    """Run a shell command inside a pod."""
    kubectl_command = ["kubectl", "exec", "-n", namespace, pod]
    if container:
        kubectl_command.extend(["-c", container])
    kubectl_command.extend(["--", "sh", "-lc", command])
    return _run(kubectl_command, timeout_seconds=timeout_seconds)


@mcp.tool()
def apply_yaml(manifest: str, timeout_seconds: int = 120) -> str:
    """Apply a YAML manifest to the cluster."""
    return _run(["kubectl", "apply", "-f", "-"], stdin=manifest, timeout_seconds=timeout_seconds)


@mcp.tool()
def delete_resource(resource: str, name: str, namespace: Optional[str] = None, timeout_seconds: int = 120) -> str:
    """Delete a Kubernetes resource."""
    command = ["kubectl", "delete", resource, name]
    if namespace:
        command.extend(["-n", namespace])
    return _run(command, timeout_seconds=timeout_seconds)


def _ensure_kubeconfig() -> None:
    if os.environ.get("KUBECONFIG"):
        return

    token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    ca_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    kubeconfig_path = Path("/tmp/kubeconfig")

    token = token_path.read_text().strip()
    server = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.environ['KUBERNETES_SERVICE_PORT']}"
    kubeconfig_path.write_text(
        f"""apiVersion: v1
kind: Config
clusters:
  - name: in-cluster
    cluster:
      server: {server}
      certificate-authority: {ca_path}
contexts:
  - name: in-cluster
    context:
      cluster: in-cluster
      user: service-account
current-context: in-cluster
users:
  - name: service-account
    user:
      token: {token}
"""
    )
    os.environ["KUBECONFIG"] = str(kubeconfig_path)


if __name__ == "__main__":
    _ensure_kubeconfig()
    mcp.run(transport="streamable-http")
