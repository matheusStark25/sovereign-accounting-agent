from __future__ import annotations

import re
import logging

LOGGER = logging.getLogger("governance.redaction")

# common patterns
REDACT_PATTERNS = [
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "[REDACTED]"),
    (re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"), "[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED]"),
    (re.compile(r"\+?\d[\d\s\-()]{6,}\d"), "[REDACTED]"),
]


def sanitize_text(s: str) -> str:
    if not s:
        return s
    out = s
    try:
        for pat, repl in REDACT_PATTERNS:
            out = pat.sub(repl, out)
    except Exception:
        LOGGER.exception("redaction failed")
    return out


class RedactionFilter(logging.Filter):
    def filter(self, record):
        try:
            record.msg = sanitize_text(str(record.getMessage()))
        except Exception:
            pass
        return True
