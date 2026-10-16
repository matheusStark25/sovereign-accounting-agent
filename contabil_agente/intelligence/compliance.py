"""Stub ComplianceChecker for local tests."""

from typing import Dict, Any


class ComplianceChecker:
    def __init__(self):
        self.name = "stub_compliance"

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # Very small heuristic: if salary present and > 0, return ok
        try:
            sal = float(data.get("salario") or data.get("amount") or 0)
            return (
                {"ok": True, "issues": []}
                if sal >= 0
                else {"ok": False, "issues": ["salario_negativo"]}
            )
        except Exception:
            return {"ok": True, "issues": []}
