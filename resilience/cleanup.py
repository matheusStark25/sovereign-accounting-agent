from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger("resilience.cleanup")

try:
    import portalocker
except Exception:
    portalocker = None


class CleanupService:
    def __init__(
        self, tmp_dir: Optional[Path] = None, retention_hours: int = 24, audit=None
    ):
        self.tmp_dir = Path(tmp_dir or Path("./.tmp"))
        self.retention = retention_hours
        self.audit = audit
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self._stop = False

    def run_pass(self):
        cutoff = time.time() - (self.retention * 3600)
        for p in list(self.tmp_dir.iterdir()):
            try:
                if p.is_dir():
                    continue
                mtime = p.stat().st_mtime
                if mtime < cutoff:
                    tomb = p.with_suffix(p.suffix + ".trash")
                    try:
                        if portalocker:
                            with portalocker.Lock(str(p), timeout=1):
                                p.replace(tomb)
                        else:
                            p.replace(tomb)
                    except Exception:
                        try:
                            tomb.write_bytes(p.read_bytes())
                            p.unlink()
                        except Exception:
                            LOGGER.exception("Failed atomic move for %s", p)
                            continue
                    # delete after grace hour
                    try:
                        tomb.unlink()
                    except Exception:
                        LOGGER.exception("Failed deleting tomb %s", tomb)
                    if self.audit:
                        try:
                            self.audit.append(
                                {"event": "cleanup_deleted", "path": str(p)}
                            )
                        except Exception:
                            pass
            except Exception:
                LOGGER.exception("Error expunging %s", p)
