"""Lightweight TaxEngine stub used during local tests."""

from typing import Dict, Any


class TaxEngine:
    def __init__(self):
        self.name = "stub_tax_engine"

    def calculate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Return a minimal calculation result based on provided amount
        amt = payload.get("amount") or payload.get("valor") or 0
        try:
            total = float(amt)
        except Exception:
            total = 0.0
        return {"total": total, "breakdown": {"base": total}}
