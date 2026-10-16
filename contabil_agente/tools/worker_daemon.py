from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict

from contabil_agente.utils.circuit_registry import EVENT_BUS_CB

logger = logging.getLogger(__name__)


def _process_message(message: Dict[str, Any]) -> None:
    """Core processing for a single task message.

    Expected message format: {"cp": "...,", "acoes": [...] }
    This function verifies the checkpoint and skips already-successful CPFs.
    """
    cpf = message.get("cp")
    try:
        from contabil_agente.tools.esocial_baixa_tool import (
            read_checkpoint,
            write_checkpoint,
        )
    except Exception:

        def read_checkpoint(cpf):
            # fallback stub when esocial_baixa_tool is unavailable
            return None

        def write_checkpoint(*a, **k):
            # fallback stub when esocial_baixa_tool is unavailable
            return None

    if not cpf:
        logger.warning("Received task without cpf: %s", message)
        return

    chk = read_checkpoint(cpf)
    if chk and chk.get("status") == "success":
        logger.info("Skipping cpf %s already successful (checkpoint)", cpf)
        return

    # Mark as in-progress
    try:
        write_checkpoint(cpf, "in_progress", last_step="worker_received")
    except Exception:
        pass

    # Wrap processing with circuit breaker for EVENT_BUS_CB
    try:

        def _do():
            # Here we would call the esocial process function. Keep it lightweight.
            logger.info("Processing cpf %s acoes=%s", cpf, message.get("acoes"))
            # Simulate processing
            time.sleep(0.5)
            # On success write checkpoint
            try:
                write_checkpoint(cpf, "success", last_step="done")
            except Exception:
                pass

        EVENT_BUS_CB.call(_do)
    except Exception as e:
        logger.exception("Processing failed for %s: %s", cpf, e)
        try:
            write_checkpoint(cpf, "failed", last_step="worker_error")
        except Exception:
            pass


def run_consumer(queue_name: str = "esocial_tasks"):
    """Run a simple consumer loop. If pika not available, consume from local file fallback."""
    use_local = (
        os.getenv("LOCAL_TASK_QUEUE_FILE") is not None
        or os.getenv("RABBIT_FAKE", "0") == "1"
    )
    if use_local:
        path = os.getenv("LOCAL_TASK_QUEUE_FILE", "local_task_queue.jsonl")
        logger.info("Worker in local-file mode reading %s", path)
        # watch the file for new lines
        seen = 0
        while True:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new = lines[seen:]
                for line in new:
                    try:
                        obj = json.loads(line)
                        _process_message(obj.get("message") or obj)
                    except Exception:
                        logger.exception("Failed to process queued line: %s", line)
                seen = len(lines)
            time.sleep(1)
    else:
        # Use RabbitMQ via pika
        try:
            # import pika dynamically to avoid static import errors when the
            # package is not installed (tools may run in environments
            # without rabbitmq client). This avoids editor/linter complaints
            # about missing module sources.
            import importlib

            pika = importlib.import_module("pika")

            params = pika.URLParameters(
                os.getenv("RABBIT_URL", "amqp://guest:guest@localhost:5672/%2F")
            )
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue=queue_name, durable=True)

            def callback(ch, method, properties, body):
                try:
                    msg = json.loads(body.decode("utf-8"))
                    _process_message(msg)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    logger.exception("Failed processing message; nack and requeue")
                    try:
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    except Exception:
                        pass

            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue=queue_name, on_message_callback=callback)
            logger.info("Worker consuming RabbitMQ queue %s", queue_name)
            ch.start_consuming()
        except Exception as e:
            logger.exception("Rabbit consumer failed to start: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_consumer()
