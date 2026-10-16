from __future__ import annotations

import importlib
import json
import logging
import os
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # for type-checkers only; runtime import is done lazily to avoid hard dependency
    # import under a different name to avoid shadowing the runtime variable
    import pika as _pika  # type: ignore  # noqa: F401


class RabbitPublisher:
    def __init__(self, url: str | None = None):
        self.url = url or os.getenv(
            "RABBIT_URL", "amqp://guest:guest@localhost:5672/%2F"
        )
        self._conn = None

    def _ensure_conn(self):
        try:
            pika = importlib.import_module("pika")
        except Exception:
            raise RuntimeError("pika not installed")

        if self._conn is None:
            params = pika.URLParameters(self.url)
            self._conn = pika.BlockingConnection(params)

    def publish(self, queue: str, message: dict) -> None:
        # try to import pika at runtime; if unavailable, fallback to local jsonl queue
        try:
            pika = importlib.import_module("pika")
        except Exception:
            path = os.getenv("LOCAL_TASK_QUEUE_FILE", "local_task_queue.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"queue": queue, "message": message}, ensure_ascii=False)
                    + "\n"
                )
            logger.info("Published message to local queue file %s", path)
            return

        self._ensure_conn()
        ch = self._conn.channel()
        ch.queue_declare(queue=queue, durable=True)
        ch.basic_publish(
            exchange="",
            routing_key=queue,
            body=json.dumps(message, ensure_ascii=False).encode("utf-8"),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        logger.info("Published message to RabbitMQ queue %s", queue)

    def close(self):
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
