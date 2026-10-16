"""ia_service - Adapter connecting ChatCore to an LLM stub and orchestrating
cognitive flow (ExtractorIA -> RangeValidator -> MemoryStore -> Calculation).

This file provides `IAAdapter` which implements a safe, testable cognitive
pipeline using the project's existing ExtractorIA, MemoryStore and RangeValidator.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from contabil_agente.chat_refactored import ChatCore

LOGGER = logging.getLogger("ia_service")


class IAAdapter:
    """Adapter that runs the cognitive pipeline and returns structured calculation.

    Behavior:
      - Attempts extraction via `ExtractorIA`.
      - If extractor returns empty (no JSON), falls back to a lightweight LLM stub
        to produce JSON (safe test stub).
      - Validates numeric ranges via `RangeValidator`.
      - Persists facts to `MemoryStore`.
      - For `rescisao` items returns a structured calculation dict with formula and steps.
    """

    def __init__(self, model_stub: Optional[Any] = None):
        self.model = model_stub or self._default_model_stub

    def _default_model_stub(self, text: str) -> str:
        """Very small deterministic stub that attempts to return a JSON string.

        NOTE: In production this should call a secure LLM endpoint with strict
        output-format constraints. For tests we keep it deterministic.
        """
        # naive stub: if text mentions 'rescisao' try to craft a minimal JSON
        if "rescisao" in text.lower() or "data_saida" in text.lower():
            # not using regex; return a conservative structure
            return json.dumps({"tipo": "rescisao"})
        return "{}"

    def process_and_compute(
        self,
        core: ChatCore,
        api_key: str,
        payload_json: str,
        jwt_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        # auth
        if not core.auth.verify_api_key(api_key):
            return {"status": 401}

        try:
            payload = json.loads(payload_json)
            session_id = payload.get("session_id")
            message = payload.get("message", "")
        except Exception:
            return {"status": 400, "reason": "invalid_payload"}

        # Extraction
        try:
            extracted = core.extractor.extract(message)
        except ValueError as ve:
            # Attempt to surface the offending field if possible
            msg = str(ve)
            field = "dados"
            if "missing key" in msg:
                try:
                    field = msg.split()[-1]
                except Exception:
                    field = "dados"
            return {
                "status": 423,
                "message": f"Dados inconsistentes para processamento contábil. Por favor, verifique [{field}].",
            }

        # If extractor returned empty, try model stub to generate JSON and parse it
        if not extracted:
            try:
                candidate = self.model(message)
                extracted = json.loads(candidate)
            except Exception:
                return {
                    "status": 423,
                    "message": "Dados inconsistentes para processamento contábil. Por favor, verifique [dados].",
                }

        # Range validation for salary (if present)
        salario = extracted.get("salario") or extracted.get("salary")
        if salario is not None:
            try:
                salario_val = float(salario)
                core.validator.validate_salary(salario_val)
            except Exception as e:
                return {
                    "status": 422,
                    "reason": "salary_validation_failed",
                    "detail": str(e),
                }

        # Persist to memory
        try:
            core.memory.store_message(session_id or "", message, extracted=extracted)
        except Exception:
            LOGGER.exception("Memory store failed")

        # If this is a rescisao calculation, compute structured result
        tipo = extracted.get("tipo") or (
            "rescisao" if extracted.get("data_saida") else None
        )
        if tipo == "rescisao":
            # require base (salario), aliquota and deducao for determinism
            if salario is None:
                return {
                    "status": 423,
                    "message": "Dados inconsistentes para processamento contábil. Por favor, verifique [salario].",
                }
            aliquota = extracted.get("aliquota")
            deducao = extracted.get("deducao")
            if aliquota is None:
                return {
                    "status": 423,
                    "message": "Dados inconsistentes para processamento contábil. Por favor, verifique [aliquota].",
                }
            if deducao is None:
                return {
                    "status": 423,
                    "message": "Dados inconsistentes para processamento contábil. Por favor, verifique [deducao].",
                }

            try:
                base = float(salario)
                aliquota_f = float(aliquota)
                deducao_f = float(deducao)
            except Exception:
                return {
                    "status": 423,
                    "message": "Dados inconsistentes para processamento contábil. Por favor, verifique [numeros].",
                }

            # Validate INSS-like discount sensible range
            try:
                core.validator.validate_inss(base * aliquota_f, base)
            except Exception as e:
                return {
                    "status": 422,
                    "reason": "inss_validation_failed",
                    "detail": str(e),
                }

            # Build formulaic response: Base * Aliquota - Dedução
            partial = base * aliquota_f
            result = partial - deducao_f
            response = {
                "status": 200,
                "calculation": {
                    "formula": {
                        "base": base,
                        "aliquota": aliquota_f,
                        "deducao": deducao_f,
                    },
                    "steps": [
                        f"Base * Aliquota = {base:.2f} * {aliquota_f:.4f} = {partial:.2f}",
                        f"{partial:.2f} - Dedução = {result:.2f}",
                    ],
                    "result": round(result, 2),
                },
            }
            return response

        # default: return accepted and stored
        return {"status": 202, "detail": "stored"}
