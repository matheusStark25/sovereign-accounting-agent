from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import date


from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
    ValidationError,
)

from .exceptions import (
    CPFInvalidoError,
    DataInvalidaError,
    ValorInvalidoError,
    RespostaInvalidaError,
)
from .configs import IASettings

LOGGER = logging.getLogger("ia_service")


CPF_RE = re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b")


def redact(text: str) -> str:
    if not text:
        return text
    t = CPF_RE.sub("[REDACTED_CPF]", text)

    def mask_name_str(s: str) -> str:
        parts = s.split()
        out = []
        for p in parts:
            if len(p) <= 2:
                out.append(p[0] + "*")
            else:
                out.append(p[0] + "*" * (len(p) - 2) + p[-1])
        return " ".join(out)

    # replace JSON name values for known keys
    for key in ("nome_trabalhador", "full_name"):
        name_re = re.compile(rf'("{key}"\s*:\s*")([^\"]+)(")')
        t = name_re.sub(
            lambda m: m.group(1) + mask_name_str(m.group(2)) + m.group(3), t
        )

    return t


class IARequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    cpf: str
    nome_trabalhador: str = None
    valor_base: Decimal
    data_inicio: date
    data_fim: date

    # aliases example
    # accept camelCase input
    @field_validator("cpf", mode="before")
    def cpf_clean(cls, v):
        if v is None:
            raise CPFInvalidoError("cpf is required")
        s = re.sub(r"\D", "", str(v))
        if len(s) != 11:
            raise CPFInvalidoError("cpf must have 11 digits")
        return s

    @field_validator("valor_base", mode="before")
    def valor_to_decimal(cls, v):
        try:
            d = Decimal(str(v))
        except Exception:
            raise ValorInvalidoError("valor_base must be numeric")
        d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if d <= Decimal("0.00"):
            raise ValorInvalidoError("valor_base must be > 0")
        return d

    @model_validator(mode="after")
    def check_dates(self):
        if self.data_inicio > self.data_fim:
            raise DataInvalidaError("data_inicio must be <= data_fim")
        return self


class IAService:
    def __init__(self, settings: IASettings | None = None):
        self.settings = settings or IASettings()
        try:
            self.settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            LOGGER.warning(
                "Cannot create log dir %s; proceeding without persistent logs",
                self.settings.LOG_DIR,
            )

    def process_json(self, json_payload: str) -> str:
        """Validate, sanitize for logging, process and return JSON result.

        Raises RespostaInvalidaError on validation problems.
        """
        try:
            # model_validate_json will raise ValidationError on problems
            model = IARequest.model_validate_json(json_payload)
        except ValidationError as e:
            # wrap as RespostaInvalidaError
            raise RespostaInvalidaError(str(e)) from e

        # Now safe to use raw data in memory for calculations; logs must be redacted
        # Use pydantic JSON serializer to handle Decimal/date safely
        try:
            dumped = model.model_dump_json(by_alias=True)
        except Exception:
            # fallback: convert decimals to str
            dd = model.model_dump(by_alias=True)
            for k, v in dd.items():
                if isinstance(v, Decimal):
                    dd[k] = str(v)
            dumped = json.dumps(dd)

        redacted = redact(dumped)
        LOGGER.info("IA request validated: %s", redacted)

        # Simulate processing: produce output with model_dump_json for performance
        out = {
            "cp": model.cpf,
            "period_days": (model.data_fim - model.data_inicio).days,
            "valor_base": str(model.valor_base),
        }

        # Before returning, ensure we don't leak PII in logs
        LOGGER.debug("IA response (redacted): %s", redact(json.dumps(out)))
        return json.dumps(out)
