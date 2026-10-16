import json
import logging
import sys
from logging import Logger


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - small util
        base = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        # `extra` is commonly injected by logging calls; guard for safety
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            base.update(extra)
        return json.dumps(base, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    # remove existing handlers to avoid duplicates in some environments
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    return root
