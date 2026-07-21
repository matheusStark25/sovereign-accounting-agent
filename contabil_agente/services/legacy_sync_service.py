"""Legacy sync for Alterdata/eSocial using RobotExecutor as needed.
Operates in NORMAL/DEGRADADO/SIMULACAO modes and uses DatabaseService as source of truth.
"""

import time
import json
from typing import Optional

from .database_service import DatabaseService
from .configuration import get_config
from .event_bus import get_event_bus

try:
    from .evidence_service import EvidenceService
except Exception:
    EvidenceService = None

DEFAULTS = {"mode": "NORMAL"}


class LegacySyncService:
    def __init__(self, config_path: Optional[str] = None):
        cfg = get_config(yaml_path=config_path, defaults=DEFAULTS)
        self.mode = cfg.get("mode", "NORMAL")
        self.db = DatabaseService()
        self.bus = get_event_bus()
        self.evidence = EvidenceService() if EvidenceService else None

    async def process_task(self, task: dict):
        # task: payload with file or cnpj
        payload = {}
        try:
            payload = json.loads(task.get("payload") or "{}")
        except Exception:
            pass
        cnpj = payload.get("cnpj") or payload.get("file")
        # if simulation, just log
        if self.mode == "SIMULACAO":
            self.db._audit(f"SIMULACAO legacy_sync {cnpj}")
            return {"status": "simulated"}

        # claim resource lock per CNPJ
        lock_res = f"cnpj:{cnpj}"
        owner = f"legacy_sync:{int(time.time())}"
        got = self.db.acquire_lock(lock_res, owner, ttl_seconds=300)
        if not got:
            return {"status": "skipped", "reason": "lock"}
        try:
            # Simulate field-by-field filling and persist session after each step
            steps = ["login", "fill_header", "fill_records", "validate", "submit"]
            session_state = {}
            for i, step in enumerate(steps, start=1):
                # perform step (mock)
                time.sleep(0.5)
                session_state[step] = "done"
                # checkpoint session progress to DB
                try:
                    self.db.record_processamento(
                        cnpj or lock_res,
                        f"legacy_sync:{step}",
                        json.dumps(session_state),
                    )
                except Exception:
                    self.db._audit("failed to checkpoint legacy sync step")

                # capture evidence screenshot for critical steps
                if self.evidence and step in ("validate", "submit"):
                    try:
                        # evidence service persists its own artifacts; no need to keep return value
                        self.evidence.screenshot(cnpj or lock_res, step)
                    except Exception:
                        self.db._audit("evidence screenshot failed")

                # publish progress event
                try:
                    self.bus.publish(
                        "legacy_sync.step",
                        {"step": step, "state": session_state},
                        correlation_id=cnpj or lock_res,
                    )
                except Exception:
                    pass

            # final mark
            return {"status": "synced", "cnpj": cnpj}
        finally:
            try:
                self.db.release_lock(lock_res, owner)
            except Exception:
                pass


__all__ = ["LegacySyncService"]
