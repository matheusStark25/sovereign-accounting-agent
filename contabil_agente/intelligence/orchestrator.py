from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict, Any
from .fsm import FSM, State
from .cache import CacheDB
from .calculator import TaxEngine
from .compliance import ComplianceChecker
from .audit import ForensicAudit

LOGGER = logging.getLogger("intelligence.orchestrator")


class IntelligenceOrchestrator:
    def __init__(self, db_path: str | None = None):
        self.cache = CacheDB(db_path)
        self.engine = TaxEngine()
        self.compliance = ComplianceChecker()
        self.audit = ForensicAudit()
        self._locks: Dict[str, asyncio.Lock] = {}

    async def handle(
        self, session_id: str, payload: Dict[str, Any], timeout: int = 30
    ) -> Dict[str, Any]:
        # enforce per-session isolation and processing lock
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise RuntimeError("session processing in progress")

        async with lock:
            fsm = FSM(session_id)
            fsm.transition(State.PROCESSANDO, "start")

            request_id = str(uuid.uuid4())

            # collect context
            fsm.transition(State.COLETANDO_CONTEXTO)
            # scoring: weight sources
            sources = payload.get("sources", [])
            # simple merge with precedence: document=0.9, message=0.5
            merged = {}
            for s in sorted(
                sources, key=lambda x: (-x.get("weight", 0), x.get("timestamp", 0))
            ):
                # if same key exists, precedence rules: weight higher wins; if same weight 0.9 prefer newer timestamp
                for k, v in s.get("data", {}).items():
                    if k not in merged:
                        merged[k] = {
                            "value": v,
                            "weight": s.get("weight", 0),
                            "ts": s.get("timestamp"),
                        }
                    else:
                        cur = merged[k]
                        if s.get("weight", 0) > cur["weight"]:
                            merged[k] = {
                                "value": v,
                                "weight": s.get("weight", 0),
                                "ts": s.get("timestamp"),
                            }
                        elif (
                            s.get("weight", 0) == cur["weight"]
                            and s.get("weight") == 0.9
                        ):
                            # precedence temporal: newer document wins
                            if s.get("timestamp", 0) > (cur.get("ts") or 0):
                                merged[k] = {
                                    "value": v,
                                    "weight": s.get("weight", 0),
                                    "ts": s.get("timestamp"),
                                }

            # extract finalized data
            final_data = {k: v["value"] for k, v in merged.items()}

            # cache with history
            self.cache.set(session_id, {"final_data": final_data}, ttl_seconds=3600)

            # validate extraction via JSON Schema placeholder
            # if extraction fails, transition to FALHA_NA_EXTRACAO and attempt one retry
            fsm.transition(State.VALIDANDO, "validate schema")
            # minimal semantic checks
            try:
                # placeholder validations
                cpf = final_data.get("cp")
                if cpf and (not isinstance(cpf, str) or len(cpf) < 5):
                    raise ValueError("cpf invalid")
            except Exception as e:
                fsm.transition(State.FALHA_NA_EXTRACAO, str(e))
                # one retry logic (pseudo-LLM call) - here we simply pass
                fsm.transition(State.AGUARDANDO_INPUT, "await manual or LLM retry")
                return {"status": "needs_manual_input", "request_id": request_id}

            # calculate
            fsm.transition(State.CALCULANDO)
            try:
                calc_res = self.engine.calculate(
                    {"amount": payload.get("amount", 0.0), "date": payload.get("date")}
                )
            except Exception as e:
                fsm.transition(State.FALHA_NA_EXTRACAO, str(e))
                return {"status": "error", "error": str(e)}

            # compliance
            comp = self.compliance.validate(final_data)

            # forensic output
            self.audit.record(
                request_id=request_id,
                session_id=session_id,
                input_sanitized=final_data,
                output={"calc": calc_res, "comp": comp},
            )

            fsm.transition(State.FINALIZADO, "done")
            return {
                "status": "ok",
                "request_id": request_id,
                "calc": calc_res,
                "comp": comp,
            }
