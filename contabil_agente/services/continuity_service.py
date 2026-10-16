"""Continuity service: environment fingerprinting and atomic recovery helpers.

Provides functions to compute a simple "DNA Digital" fingerprint and
to perform atomic checkpoint flushes used during shutdown/startup.
"""

import hashlib
import json
import os
import platform
import time
import logging

logger = logging.getLogger("continuity_service")


def compute_environment_dna() -> str:
    """Compute a compact fingerprint of the environment (OS, hostname,
    selected file mtimes). Intended as a tamper-detection signal.
    """
    data = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "node": platform.node(),
        "python": platform.python_version(),
    }
    # include quick checksums of key legacy exe paths if present
    candidates = [r"C:\\Program Files\\LegacySintegra\\sintegra.exe", "/usr/bin/sedif"]
    extras = {}
    for p in candidates:
        try:
            if os.path.exists(p):
                extras[p] = os.path.getmtime(p)
        except Exception:
            continue
    data["paths"] = extras
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_checkpoint(db, tag: str = None) -> None:
    """Force DB to persist WAL checkpoint and create a small named snapshot file.

    db: an instance of DatabaseService
    """
    try:
        now = int(time.time())
        s = tag or str(now)
        db._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        db._conn.commit()
        # write marker
        marker = os.path.join(os.path.dirname(db.db_path), f"checkpoint.{s}.marker")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now, "dna": compute_environment_dna()}))
        logger.info("atomic_checkpoint_created %s", marker)
    except Exception:
        logger.exception("atomic_checkpoint_failed")


__all__ = ["compute_environment_dna", "atomic_checkpoint"]
