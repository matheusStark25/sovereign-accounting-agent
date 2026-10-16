import contextvars
import logging
from typing import Optional

# Context variable to hold correlation id across async tasks/threads
correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(cid: Optional[str]) -> None:
    correlation_id_var.set(cid)


def get_correlation_id() -> Optional[str]:
    return correlation_id_var.get()


class CorrelationLoggerAdapter(logging.LoggerAdapter):
    """LoggerAdapter that injects `correlation_id` into all log records as extra."""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        cid = get_correlation_id()
        if cid is not None:
            extra = dict(extra)
            extra["correlation_id"] = cid
            kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> CorrelationLoggerAdapter:
    base = logging.getLogger(name)
    return CorrelationLoggerAdapter(base, {})
