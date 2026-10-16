from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("cadastral_validator")

# Guarded import for external connectors (SEFAZ or other gov connectors)
try:
    from contabil_agente.services.sefaz_connector import SefazConnector
except Exception:
    SefazConnector = None


class CadastralValidator:
    """Performs cadastral/identity validations and PII anonymization.

    - Validates basic formats (CNPJ/CPF)
    - Optionally calls external gov connectors for live status
    - Returns normalized payload and decision
    """

    CPF_RE = re.compile(r"^(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})$")
    CNPJ_RE = re.compile(r"^(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})$")

    def __init__(self, connector: Optional[Any] = None, db: Optional[Any] = None):
        self.connector = connector or (SefazConnector() if SefazConnector else None)
        self.db = db

    async def validate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate payload asynchronously.

        Returns: {ok: bool, reason: Optional[str], normalized: dict}
        """
        # quick synchronous checks
        try:
            cnpj = payload.get("cnpj") or payload.get("company_cnpj")
            cpf = payload.get("cp") or payload.get("person_cpf")

            if cnpj:
                if not self._valid_cnpj(cnpj):
                    return {
                        "ok": False,
                        "reason": "invalid_cnpj",
                        "normalized": payload,
                    }
            if cpf:
                if not self._valid_cpf(cpf):
                    return {"ok": False, "reason": "invalid_cp", "normalized": payload}

            # optionally call external connector for live check
            if self.connector and (cnpj or cpf):
                try:
                    # connector may expose an async lookup method
                    if asyncio.iscoroutinefunction(self.connector.lookup):
                        status = await self.connector.lookup(cnpj=cnpj, cpf=cpf)
                    else:
                        # run in threadpool to avoid blocking
                        loop = asyncio.get_event_loop()
                        status = await loop.run_in_executor(
                            None, lambda: self.connector.lookup(cnpj=cnpj, cpf=cpf)
                        )
                    if not status or not status.get("active", True):
                        return {
                            "ok": False,
                            "reason": "gov_lookup_negative",
                            "normalized": payload,
                        }
                except Exception:
                    logger.exception(
                        "gov lookup failed; proceeding with best-effort for payload"
                    )

            # normalized minimal set
            normalized = {"cnpj": cnpj, "cpf": cpf}
            return {"ok": True, "reason": None, "normalized": normalized}
        except Exception:
            logger.exception("validation unexpected error")
            return {"ok": False, "reason": "validation_error", "normalized": payload}

    def anonymize_pii(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy with CPF/CNPJ masked (keeps last 4 digits)."""
        out = dict(payload)
        if "cp" in out and out["cp"]:
            s = re.sub(r"\D", "", str(out["cp"]))
            out["cp"] = ("*" * max(0, len(s) - 4)) + s[-4:]
        if "cnpj" in out and out["cnpj"]:
            s = re.sub(r"\D", "", str(out["cnpj"]))
            out["cnpj"] = ("*" * max(0, len(s) - 4)) + s[-4:]
        return out

    def _valid_cpf(self, cpf: str) -> bool:
        if not cpf:
            return False
        s = re.sub(r"\D", "", str(cpf))
        return bool(self.CPF_RE.match(cpf) or len(s) == 11)

    def _valid_cnpj(self, cnpj: str) -> bool:
        if not cnpj:
            return False
        s = re.sub(r"\D", "", str(cnpj))
        return bool(self.CNPJ_RE.match(cnpj) or len(s) == 14)


__all__ = ["CadastralValidator"]
