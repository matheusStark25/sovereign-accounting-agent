from __future__ import annotations

try:
    import yaml  # type: ignore[reportMissingImports]

    _YAML_AVAILABLE = True
except Exception:
    yaml = None
    _YAML_AVAILABLE = False
import logging
from typing import Dict, Any

LOGGER = logging.getLogger("intelligence.compliance")


class ComplianceChecker:
    def __init__(self, rules_path: str = None):
        self.rules_path = rules_path or "rules/compliance_rules.yaml"
        try:
            with open(self.rules_path, "r", encoding="utf-8") as fh:
                self.rules = yaml.safe_load(fh)
        except Exception:
            LOGGER.warning("Compliance rules not found at %s", self.rules_path)
            self.rules = {}

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # minimal implementation: check presence of required fields
        issues = []
        required = self.rules.get("required", []) if self.rules else []
        for r in required:
            if r not in data:
                issues.append({"field": r, "issue": "missing"})
        # placeholder for CNAE/regime compatibility
        return {"ok": len(issues) == 0, "issues": issues}
