from __future__ import annotations

import hmac
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

LOGGER = logging.getLogger("governance.audit")


class AuditLogger:
    def __init__(self, path: Optional[Path] = None, hmac_key: Optional[bytes] = None):
        self.path = Path(path or "./logs/audit/access.log")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hmac_key = hmac_key or b""

    def append(self, entry: Dict[str, Any]):
        payload = {**entry}
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        sig = self._sign(line)
        to_write = json.dumps({"entry": payload, "hmac": sig}, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(to_write + "\n")

    def _sign(self, s: str) -> str:
        try:
            if not self.hmac_key:
                return ""
            mac = hmac.new(self.hmac_key, s.encode("utf-8"), hashlib.sha256).hexdigest()
            return mac
        except Exception:
            LOGGER.exception("HMAC sign failed")
            return ""

    def verify_line(self, line: str) -> bool:
        try:
            obj = json.loads(line)
            entry = obj.get("entry")
            sig = obj.get("hmac", "")
            recomputed = self._sign(
                json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
            )
            return hmac.compare_digest(recomputed, sig)
        except Exception:
            return False
