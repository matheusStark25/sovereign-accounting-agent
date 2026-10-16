from __future__ import annotations

import logging
import re
from typing import Pattern


class RedactionFilter(logging.Filter):
    """Redacts sensitive patterns from log messages.

    Applies simple regex substitutions to the formatted message.
    """

    CNPJ_RE: Pattern = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
    PATH_RE: Pattern = re.compile(r"([A-Za-z]+:)?(\\[\w .-]+)+\\?")
    SECRET_RE: Pattern = re.compile(
        r"(password|senha|pass|token|secret)\s*[:=]\s*[^\s,]+", re.I
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            redacted = self.CNPJ_RE.sub("<CNPJ_REDACTED>", msg)
            redacted = self.PATH_RE.sub("<PATH>", redacted)
            redacted = self.SECRET_RE.sub(r"\1=<REDACTED>", redacted)
            # overwrite msg and args to avoid double-format
            record.msg = redacted
            record.args = ()
        except Exception:
            pass
        return True
