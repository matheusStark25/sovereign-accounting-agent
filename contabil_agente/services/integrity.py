from __future__ import annotations

import hashlib
import json
import os
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Optional

try:
    from contabil_agente.utils.logging_adapter import get_logger, set_correlation_id
except ImportError:
    from utils.logging_adapter import get_logger, set_correlation_id

logger = get_logger(__name__)


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _publish_failure(cid: Optional[str], reason: str, payload: Dict[str, Any]) -> None:
    # Publish a failure event and persist checkpoint if DatabaseService available.
    try:
        # local import to avoid circulars
        try:
            from contabil_agente.services.event_bus import get_event_bus
            from contabil_agente.services.database_service import DatabaseService
        except ImportError:
            from services.event_bus import get_event_bus
            from services.database_service import DatabaseService

        bus = get_event_bus()
        # best-effort publish
        try:
            bus.publish(
                "document.processing_failed",
                {"reason": reason, "payload": payload},
                correlation_id=cid,
            )
        except Exception:
            logger.exception("failed to publish processing_failed for %s", cid)

        try:
            db = DatabaseService()
            db.record_processamento(cid, "FAILED", json.dumps({"reason": reason}))
        except Exception:
            logger.debug("no db to record FAILED %s", cid)
    except Exception:
        # Swallow anything here to preserve original flow
        logger.exception("_publish_failure encountered an error")


def verify_artifact_integrity(func: Callable[[Dict[str, Any]], Awaitable[Any]]):
    """Decorator for async event handlers that verifies artifact hash integrity.

    Expects event: Dict with optional `payload` that may contain:
      - artifact_data (bytes or str)
      - artifact_path (filesystem path)
      - artifact_hashes (list of hex digests)

    On missing artifact or mismatch, publishes a failure and records FAILED checkpoint.
    """

    @wraps(func)
    async def wrapper(event: Dict[str, Any]):
        cid = event.get("correlation_id")
        # set correlation id for downstream logs
        set_correlation_id(cid)
        payload = event.get("payload", {}) or {}

        artifact_hashes = payload.get("artifact_hashes")
        if artifact_hashes:
            try:
                # obtain raw bytes
                if "artifact_data" in payload:
                    raw = payload["artifact_data"]
                    if isinstance(raw, str):
                        raw = raw.encode("utf-8")
                elif "artifact_path" in payload:
                    path = payload["artifact_path"]
                    if not os.path.exists(path):
                        reason = "ARTIFACT_NOT_FOUND"
                        logger.error("%s: %s", reason, path)
                        _publish_failure(cid, reason, payload)
                        return
                    with open(path, "rb") as fh:
                        raw = fh.read()
                else:
                    reason = "ARTIFACT_NOT_FOUND"
                    logger.error("%s: no artifact_data or artifact_path", cid)
                    _publish_failure(cid, reason, payload)
                    return

                computed = _compute_sha256(raw)
                if computed not in artifact_hashes:
                    reason = "INTEGRITY_MISMATCH"
                    logger.error(
                        "Integrity mismatch for %s expected=%s computed=%s",
                        cid,
                        artifact_hashes,
                        computed,
                    )
                    _publish_failure(cid, reason, payload)
                    return
            except Exception as e:
                logger.exception("artifact integrity verification failed: %s", e)
                _publish_failure(cid, "INTEGRITY_ERROR", payload)
                return

        # call original handler
        return await func(event)

    return wrapper
