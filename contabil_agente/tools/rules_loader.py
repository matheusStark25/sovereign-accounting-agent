import os
import logging
from decimal import Decimal
import re
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


class RuleNotFoundError(Exception):
    pass


def _parse_decimal_str(s: Any) -> Decimal:
    if s is None:
        return Decimal("0.00")
    if isinstance(s, Decimal):
        return s
    try:
        t = str(s).strip()
        t = t.replace("R$", "").replace("r$", "").strip()
        if "," in t and "." in t:
            t = t.replace(".", "").replace(",", ".")
        elif "," in t and "." not in t:
            t = t.replace(",", ".")
        return Decimal(t)
    except Exception:
        try:
            return Decimal(str(float(s)))
        except Exception:
            return Decimal("0.00")


def _convert(obj: Any, key_hint: str = "") -> Any:
    """Recursively convert numeric-like strings to Decimal.

    Heurística: converte automaticamente chaves tipicamente usadas como
    percentuais (ex: 'rate', 'aliquota', 'periculosidade', 'standard_rate', etc.)
    em frações (ex: '30.00' -> Decimal('0.30')). Isso facilita manutenção de
    regras sem exigir nomenclatura rígida.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = _convert(v, key_hint=k)
        return out
    if isinstance(obj, list):
        return [_convert(x, key_hint=key_hint) for x in obj]
    # Scalars
    if isinstance(obj, (int, float)):
        return Decimal(str(obj))
    if isinstance(obj, str):
        s = obj.strip()
        # Empty
        if s == "":
            return s
        # If string contains non-numeric characters (letters other than currency symbol),
        # avoid attempting numeric conversion to prevent Decimal exceptions.
        # Allow digits, dot, comma, minus and currency symbol R$
        if not re.match(r"^[0-9\.,\-\sR\$]+$", s):
            return s

        # Numeric-like
        try:
            dec = _parse_decimal_str(s)
        except Exception:
            return s
        # Keys that should be interpreted as percent values (treated as 0..100 in YAML)
        PERCENT_KEYS = {
            "rate",
            "aliquota",
            "percent",
            "percentage",
            "periculosidade",
            "hora_extra_min",
            "adicional_noturno",
            "standard_rate",
            "apprentice_rate",
            "vt_max_discount",
            "max_discount_total",
            "alimony_max_percent",
            "fgts_fine_standard",
            "fgts_fine_agreed",
            "fgts_standard_rate",
            "fgts_apprentice_rate",
        }

        if key_hint.lower() in PERCENT_KEYS:
            try:
                # Convert percentage number into fractional Decimal (e.g., 30.00 -> 0.30)
                return (dec / Decimal("100")).quantize(Decimal("0.0000001"))
            except Exception:
                return dec
        return dec
    return obj


class RulesLoader:
    """Loader for YAML rule files in `rules/` directory.

    Usage: loader = RulesLoader(rules_dir=path); rules = loader.load_all()
    """

    def __init__(self, rules_dir: str = None):
        self.rules_dir = rules_dir or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "rules")
        )

    def _read_yaml(self, filename: str) -> Dict[str, Any]:
        path = os.path.join(self.rules_dir, filename)
        if not os.path.exists(path):
            logger.error("Rules file not found: %s", path)
            raise RuleNotFoundError(f"Rules file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
                if raw is None:
                    raise RuleNotFoundError(f"Rules file empty or invalid YAML: {path}")
                return raw
        except yaml.YAMLError as e:
            logger.exception("YAML parse error in %s", path)
            raise RuleNotFoundError(f"YAML parse error in {path}: {e}")

    def load_all(self) -> Dict[str, Any]:
        """Load known rules files and convert numerics to Decimal."""
        loaded = {}
        # Load tax rules first
        tax = self._read_yaml("tax_rules.yaml")
        loaded["tax"] = _convert(tax)

        # Compliance contains many textual fields and event codes — keep raw to
        # avoid aggressive numeric parsing that may mis-handle free-form text.
        compliance = self._read_yaml("compliance_rules.yaml")
        loaded["compliance"] = compliance

        # Basic validation: ensure INSS ceiling exists
        ceiling = None
        if "charges_and_fines" in loaded["tax"]:
            ceiling = loaded["tax"]["charges_and_fines"].get("ceiling_inss")
        if not ceiling:
            # Legacy path: employee_inss_table.ceiling
            ceiling = loaded["tax"].get("employee_inss_table", {}).get("ceiling")
        if not ceiling:
            logger.error("Missing INSS ceiling in tax rules")
            raise RuleNotFoundError("Missing INSS ceiling in tax_rules.yaml")

        return loaded
