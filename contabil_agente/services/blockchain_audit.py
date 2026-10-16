"""Append-only audit trail with optional anchoring to external chain.

This module maintains an append-only local log and computes a Merkle-like
rolling root. Optionally, when `BLOCKCHAIN_HTTP_ENDPOINT` is configured,
it will POST small anchoring transactions. This is an immutable local
audit ledger (stored as newline-delimited JSON). For production, replace
anchoring with a proper blockchain service or an L1 attestation.
"""

import os
import json
import hashlib
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("blockchain_audit")

AUDIT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "audit")
os.makedirs(AUDIT_DIR, exist_ok=True)
AUDIT_FILE = os.path.join(AUDIT_DIR, "audit.log")


def append_audit(entry: Dict[str, Any]) -> str:
    """Append entry and return its local hash (hex)."""
    try:
        serialized = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        rec = {"hash": h, "entry": entry}
        with open(AUDIT_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # optionally anchor
        endpoint = os.getenv("BLOCKCHAIN_HTTP_ENDPOINT")
        if endpoint:
            try:
                requests.post(endpoint, json={"anchor": h}, timeout=3)
            except Exception:
                logger.exception("anchor_failed")
        return h
    except Exception:
        logger.exception("audit_append_failed")
        return ""


def compute_rolling_root() -> str:
    """Compute a simple rolling root across the stored audit file."""
    h = hashlib.sha256()
    try:
        if not os.path.exists(AUDIT_FILE):
            return ""
        with open(AUDIT_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    h.update(obj.get("hash", "").encode("utf-8"))
                except Exception:
                    continue
        return h.hexdigest()
    except Exception:
        logger.exception("compute_root_failed")
        return ""


__all__ = ["append_audit", "compute_rolling_root"]
