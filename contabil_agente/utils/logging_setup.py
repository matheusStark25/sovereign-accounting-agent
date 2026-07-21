from __future__ import annotations

import logging
import sys

from contabil_agente.utils.log_redactor import RedactionFilter
from contabil_agente.utils.logging_adapter import get_logger


def init_logging():
    root = logging.getLogger()
    # attach redaction filter globally
    root.addFilter(RedactionFilter())

    # ensure unhandled exceptions include correlation id via our adapter
    def _excepthook(exc_type, exc_value, exc_tb):
        log = get_logger("unhandled")
        log.exception("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _excepthook
    # Monkeypatch logging.getLogger to return our correlation-aware adapter
    _orig_get_logger = logging.getLogger

    def _get_logger(name=None):
        try:
            return get_logger(name or "root")
        except Exception:
            return _orig_get_logger(name)

    logging.getLogger = _get_logger
