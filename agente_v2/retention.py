from __future__ import annotations
import os
import time
 

from .audit import AuditLogger


async def run_retention(
    base_dir: str = ".data/storage",
    max_age_seconds: int = 60 * 60 * 24 * 30,
    audit: AuditLogger | None = None,
):
    """Delete files older than max_age_seconds under base_dir and emit audit entries."""
    if audit is None:
        audit = AuditLogger()
    now = time.time()
    deleted = 0
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            path = os.path.join(root, f)
            try:
                m = os.path.getmtime(path)
                if (now - m) > max_age_seconds:
                    os.remove(path)
                    deleted += 1
                    await audit.record(
                        "retention:deleted", None, "retention-job", {"path": path}
                    )
            except Exception:
                continue
    return {"deleted": deleted}
