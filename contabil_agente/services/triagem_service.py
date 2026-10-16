"""Triagem (ingest) service: scans input folder, computes SHA-256 and enqueues tasks.
Modes: NORMAL, DEGRADADO, SIMULACAO
"""

import os
import hashlib
from pathlib import Path
from typing import Dict, Optional

from .database_service import DatabaseService
from .configuration import get_config
from .event_bus import get_event_bus
import random
import uuid
import asyncio

DEFAULTS = {
    "input_dir": os.path.join(os.path.dirname(__file__), "..", "incoming"),
    "mode": "NORMAL",
}


class TriagemService:
    def __init__(self, config_path: Optional[str] = None):
        cfg = get_config(yaml_path=config_path, defaults=DEFAULTS)
        self.input_dir = cfg.get("input_dir")
        self.mode = cfg.get("mode", "NORMAL")
        self.db = DatabaseService()
        self.bus = get_event_bus()

    def _sha256(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def scan_and_enqueue(self) -> Dict[str, int]:
        out = {"found": 0, "enqueued": 0}
        p = Path(self.input_dir)
        if not p.exists():
            return out
        for f in p.iterdir():
            if f.is_file():
                out["found"] += 1
                sha = self._sha256(str(f))
                if self.mode == "SIMULACAO":
                    # only log
                    self.db._audit(f"SIMULACAO triagem found {f} sha={sha}")
                    continue
                # try classification with a scoring model (mocked here)
                score, decision = self.classificar_documento(str(f))
                correlation_id = str(uuid.uuid4())
                payload = {
                    "file": str(f),
                    "orig_sha": sha,
                    "score": score,
                    "decision": decision,
                }

                # save classification decision
                try:
                    self.db.save_classification_decision(
                        correlation_id, "triagem_v1", score, decision, payload
                    )
                except Exception:
                    self.db._audit("failed to save classification decision")

                # publish triage result event
                try:
                    # if low confidence send to UNCLASSIFIED
                    if score < 0.85:
                        awaitable = self.bus.publish(
                            "document.triage_result",
                            {"decision": "UNCLASSIFIED", **payload},
                            correlation_id=correlation_id,
                        )
                    else:
                        # decision DP or FISCAL
                        awaitable = self.bus.publish(
                            "document.triage_result",
                            {"decision": decision, **payload},
                            correlation_id=correlation_id,
                        )
                    # ensure publish scheduled
                    # if coroutine returned, schedule it
                    if asyncio.iscoroutine(awaitable):
                        asyncio.create_task(awaitable)
                except Exception:
                    # fallback: enqueue into tasks table to be picked by batch manager
                    dept = "FISCAL" if decision == "FISCAL" else "DP"
                    self.db.enqueue_task(
                        cnpj=sha,
                        payload={
                            "file": str(f),
                            "dept": dept,
                            "orig_sha": sha,
                            "correlation_id": correlation_id,
                        },
                        priority="URGENTE" if dept == "FISCAL" else "BATCH",
                    )
                out["enqueued"] += 1
        return out

    def classificar_documento(self, filepath: str) -> tuple[float, str]:
        """Mock classification: returns (score, decision).

        Implementação real deve residir em modelos configurados via YAML.
        """
        # lightweight heuristic: xml -> FISCAL, else DP, with a confidence score
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".xml", ".nfe"):
            base_score = 0.92
            decision = "FISCAL"
        else:
            base_score = 0.9
            decision = "DP"
        # add small randomness for simulation
        score = base_score - (random.random() * 0.05)
        return float(score), decision


__all__ = ["TriagemService"]
