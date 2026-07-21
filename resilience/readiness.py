from __future__ import annotations

import shutil
import os
import logging
from typing import Any, Dict

LOGGER = logging.getLogger("resilience.readiness")


def disk_usage_percent(path: str = ".") -> float:
    try:
        du = shutil.disk_usage(path)
        return du.used / du.total * 100.0 if du.total else 0.0
    except Exception:
        return 0.0


def inode_usage_percent(path: str = ".") -> float:
    # Unix-only statvfs; on Windows, return 0.0
    try:
        st = os.statvfs(path)
        free = st.f_bfree
        total = st.f_files
        if total:
            used = total - free
            return used / total * 100.0
    except Exception:
        return 0.0
    return 0.0


def readiness_check(
    services: Dict[str, Any],
    disk_threshold: float = 90.0,
    inode_threshold: float = 95.0,
) -> Dict[str, Any]:
    # services may provide: vault, redis, queue
    du = disk_usage_percent()
    iu = inode_usage_percent()
    if du > disk_threshold:
        return {"status": "unavailable", "reason": "disk_full", "disk_usage": du}
    if iu and iu > inode_threshold:
        return {
            "status": "unavailable",
            "reason": "inodes_exhausted",
            "inode_usage": iu,
        }

    # vault health
    vault = services.get("vault")
    if vault and not vault.health():
        return {"status": "unavailable", "reason": "vault_unhealthy"}

    # redis health
    redis = services.get("redis")
    try:
        if redis:
            ok = redis.ping()
            if not ok:
                return {"status": "unavailable", "reason": "redis_unreachable"}
    except Exception:
        return {"status": "unavailable", "reason": "redis_error"}

    # queue latency (if supported)
    queue = services.get("queue")
    if queue:
        try:
            qsize = queue.queue_size()
            if qsize > 1000:
                return {
                    "status": "unavailable",
                    "reason": "queue_saturated",
                    "queue_size": qsize,
                }
        except Exception:
            pass

    return {"status": "ready"}
