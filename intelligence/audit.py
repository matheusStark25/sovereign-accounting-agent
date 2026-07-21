from __future__ import annotations

import json
import hashlib
import time
import logging
from pathlib import Path
from typing import Dict, Any

LOGGER = logging.getLogger("intelligence.audit")


class ForensicAudit:
    def __init__(self, path: str = "logs/forensic_audit.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        request_id: str,
        session_id: str,
        input_sanitized: Dict[str, Any],
        output: Dict[str, Any],
    ):
        payload = {
            "timestamp": int(time.time()),
            "request_id": request_id,
            "session_id": session_id,
            "input_sanitized": input_sanitized,
            "output_hash": hashlib.sha256(
                json.dumps(output, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            LOGGER.info("Forensic audit recorded %s", request_id)
        except PermissionError as e:
            # Log the failure but do not raise: auditing should be best-effort
            LOGGER.warning("Forensic audit write failed (%s): %s", self.path, e)
        except Exception as e:
            LOGGER.exception("Unexpected error while recording forensic audit: %s", e)
