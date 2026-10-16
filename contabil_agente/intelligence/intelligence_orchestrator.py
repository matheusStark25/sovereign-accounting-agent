"""Lightweight IntelligenceOrchestrator stub for local tests.

Provides an async `handle(session_id, payload, timeout=30)` method that
returns a predictable structure used by `chat_refactored`.
"""

from __future__ import annotations
import asyncio
from typing import Any, Dict


class IntelligenceOrchestrator:
    def __init__(self):
        # minimal init
        self.name = "stub_orchestrator"

    async def handle(
        self, session_id: str, payload: Dict[str, Any], timeout: int = 30
    ) -> Dict[str, Any]:
        """Simulate orchestration work and return a predictable result.

        - If payload contains an "amount" key, return a calc dict with total equal to amount.
        - Otherwise return minimal ok.
        """
        # simulate small async work
        await asyncio.sleep(0)
        amount = payload.get("amount")
        if amount:
            try:
                total = float(amount)
            except Exception:
                total = 0.0
            return {"status": "ok", "calc": {"total": total}, "comp": {"ok": True}}
        return {"status": "ok"}
