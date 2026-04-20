#!/usr/bin/env python3
"""OOM AutoFix Operator — Kopf controller that patches Deployments after OOMKilled."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional, Tuple

import kopf
from kubernetes import client, config

try:
    from kubernetes.client.exceptions import ApiException
except ImportError:  # pragma: no cover
    from kubernetes.client.rest import ApiException  # type: ignore

# -----------------------------------------------------------------------------
# Config (from Helm / downward API)
# -----------------------------------------------------------------------------

SCALE_FACTOR = float(os.environ.get("SCALE_FACTOR", "2.25"))
MAX_MEMORY_MIB = int(float(os.environ.get("MAX_MEMORY_GI", "2")) * 1024)
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "app")
LOG_LEVEL = int(os.environ.get("LOG_LEVEL", "8"))
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "").strip()

logging.basicConfig(
    level=logging.DEBUG if LOG_LEVEL >= 8 else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("oom-autofix")

config.load_incluster_config()
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()

_MEM_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*([KMGTPE]i?)?\s*$", re.IGNORECASE
)


def memory_string_to_mib(s: str) -> Optional[int]:
    """Parse Kubernetes quantity-like memory string to integer MiB."""
    if not s:
        return None
    m = _MEM_RE.match(s)
    if not m:
        return None
    num = float(m.group(1))
    suffix = (m.group(2) or "Mi").lower()
    if suffix == "ki":
        return max(1, int(num / 1024))
    if suffix == "mi":
        return max(1, int(num))
    if suffix == "gi":
        return max(1, int(num * 1024))
    if suffix == "ti":
        return max(1, int(num * 1024 * 1024))
    if suffix == "k":
        return max(1, int(num / (1024 * 1024)))
    if suffix == "m":
        return max(1, int(num / 1024))
    if suffix == "g":
        return max(1, int(num * (1000**3) / (1024**2)))
    if suffix == "t":
        return max(1, int(num * (1000**4) / (1024**2)))
    return max(1, int(num))


def find_deployment_for_pod(namespace: str, pod_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve Deployment name from Pod via ReplicaSet owner chain."""
    pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    rs_name = None
    for ref in pod.metadata.owner_references or []:
        if ref.kind == "ReplicaSet":
            rs_name = ref.name
            break
    if not rs_name:
        return None, None
    rs = apps_v1.read_namespaced_replica_set(name=rs_name, namespace=namespace)
    for ref in rs.metadata.owner_references or []:
        if ref.kind == "Deployment":
            return ref.name, namespace
    return None, None


def patch_deployment_memory(namespace: str, deploy_name: str, new_mib: int) -> None:
    """Strategic-merge patch container memory limit by container name."""
    body: dict[str, Any] = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": CONTAINER_NAME,
                            "resources": {"limits": {"memory": f"{new_mib}Mi"}},
                        }
                    ]
                }
            }
        }
    }
    apps_v1.patch_namespaced_deployment(
        name=deploy_name,
        namespace=namespace,
        body=body,
    )


@kopf.on.startup()
def on_startup(**_: Any) -> None:
    print("🚀 ACTIVE")
    if PROMETHEUS_URL:
        logger.info("PROMETHEUS_URL is set: %s", PROMETHEUS_URL)


@kopf.on.event("v1", "pods")
def pod_event(body: dict[str, Any], event: dict[str, Any], **_: Any) -> None:
    if event.get("type") == "DELETED":
        return

    namespace = body.get("metadata", {}).get("namespace") or "default"
    name = body.get("metadata", {}).get("name") or ""
    phase = body.get("status", {}).get("phase")

    statuses = body.get("status", {}).get("containerStatuses") or []
    oom = False
    for cs in statuses:
        last = (cs.get("lastState") or {}).get("terminated") or {}
        if last.get("reason") == "OOMKilled":
            oom = True
            break
        state = (cs.get("state") or {}).get("terminated") or {}
        if state.get("reason") == "OOMKilled":
            oom = True
            break

    if not oom:
        return

    logger.info("🔔 OOM DETECTED pod=%s/%s phase=%s", namespace, name, phase)

    deploy_name, ns = find_deployment_for_pod(namespace, name)
    if not deploy_name or not ns:
        logger.warning("No owning Deployment found for pod %s/%s", namespace, name)
        return

    try:
        dep = apps_v1.read_namespaced_deployment(name=deploy_name, namespace=ns)
    except ApiException as e:
        logger.exception("read deployment failed: %s", e)
        return

    cur_mib: Optional[int] = None
    for c in dep.spec.template.spec.containers or []:
        if c.name == CONTAINER_NAME:
            lim = (c.resources.limits or {}).get("memory") if c.resources else None
            if lim:
                cur_mib = memory_string_to_mib(lim)
            break

    if cur_mib is None:
        cur_mib = 400
    new_mib = min(int(cur_mib * SCALE_FACTOR), MAX_MEMORY_MIB)
    if new_mib <= cur_mib:
        logger.info("Skip patch: computed limit %sMi not above current %sMi", new_mib, cur_mib)
        return

    try:
        patch_deployment_memory(ns, deploy_name, new_mib)
        logger.info("✅ PATCHED to %sMi deployment=%s/%s", new_mib, ns, deploy_name)
    except ApiException as e:
        logger.exception("patch failed: %s", e)
