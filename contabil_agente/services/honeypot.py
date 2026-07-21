"""Simple honeypot traps to detect tampering attempts.

Creates files and markers that, if accessed, will emit high-severity
alerts. The files are intentionally misleading and monitored.
"""

import os
import logging
import time

logger = logging.getLogger("honeypot")


def setup_honeypot(base_path: str):
    traps_dir = os.path.join(base_path, "honeypot")
    try:
        os.makedirs(traps_dir, exist_ok=True)
        # create a decoy key file
        decoy = os.path.join(traps_dir, "private_keys.txt")
        if not os.path.exists(decoy):
            with open(decoy, "w", encoding="utf-8") as fh:
                fh.write("DO NOT OPEN\nThis is a decoy file. Access will be logged.\n")
        # creation timestamp
        ts = int(time.time())
        with open(os.path.join(traps_dir, "created.ts"), "w") as fh:
            fh.write(str(ts))
    except Exception:
        logger.exception("honeypot_setup_failed")


def check_honeypot_access(base_path: str) -> bool:
    traps_dir = os.path.join(base_path, "honeypot")
    decoy = os.path.join(traps_dir, "private_keys.txt")
    try:
        if os.path.exists(decoy):
            # heuristics: if file was modified after creation, flag
            created = os.path.getmtime(os.path.join(traps_dir, "created.ts"))
            m = os.path.getmtime(decoy)
            if m > created + 1:
                logger.warning("honeypot_access_detected %s", decoy)
                return True
    except Exception:
        logger.exception("honeypot_check_failed")
    return False


__all__ = ["setup_honeypot", "check_honeypot_access"]
