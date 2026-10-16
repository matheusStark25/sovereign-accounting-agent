from __future__ import annotations

import logging
from typing import Any, Optional, Callable

from contabil_agente.utils.circuit_registry import DB_CB, EVENT_BUS_CB
from contabil_agente.services.event_bus import get_event_bus

logger = logging.getLogger("contabil_agente.database_adapter")


class DatabaseAdapter:
    """Thin adapter around DatabaseService providing CAS-like helpers

    Methods implemented are defensive: they try to use underlying
    DatabaseService capabilities where available, otherwise fall back
    to best-effort behaviors while logging clearly.
    """

    def __init__(self, db: Any):
        self._db = db
        self._bus = get_event_bus()

    def record_processamento(self, *args, **kwargs):
        def _call():
            return self._db.record_processamento(*args, **kwargs)

        return DB_CB.call(_call)

    def insert_outbox_event(
        self, event_name: str, correlation_id: str, body: str
    ) -> None:
        # Prefer DB outbox insert when present
        if hasattr(self._db, "insert_outbox_event"):

            def _call():
                return self._db.insert_outbox_event(event_name, correlation_id, body)

            try:
                return DB_CB.call(_call)
            except Exception:
                logger.exception("insert_outbox_event circuit breaker or call failed")

        # fallback: publish via event bus (best-effort)
        try:
            EVENT_BUS_CB.call(
                self._bus.publish, event_name, body, correlation_id=correlation_id
            )
        except Exception:
            logger.exception("fallback publish for outbox event failed")

    def execute_in_transaction(self, fn: Callable[[Any], Any]) -> Any:
        # If underlying DB offers transactional API, use it; else try to run fn
        if hasattr(self._db, "execute_in_transaction"):

            def _call():
                return self._db.execute_in_transaction(fn)

            return DB_CB.call(_call)

        if hasattr(self._db, "transaction"):

            def _call():
                with self._db.transaction():
                    return fn(self._db)

            return DB_CB.call(_call)

        # last-resort: call without transaction
        try:
            return DB_CB.call(fn, self._db)
        except Exception:
            logger.exception("execute_in_transaction unavailable and call failed")
            raise

    # Worker CAS helpers
    def get_worker_info(self, worker_id: str) -> Optional[dict]:
        if hasattr(self._db, "get_worker_info"):

            def _call():
                return self._db.get_worker_info(worker_id)

            try:
                return DB_CB.call(_call)
            except Exception:
                logger.exception("get_worker_info failed via circuit breaker")
                return None

        # fallback to check_workers
        try:
            res = DB_CB.call(self._db.check_workers)
            # try to find the worker entry
            for entry in (res.get("restart") or []) + (res.get("quarantined") or []):
                if entry == worker_id:
                    return {"worker_id": worker_id}
            return None
        except Exception:
            logger.exception("fallback get_worker_info failed")
            return None

    def compare_and_update_worker_owner(
        self, worker_id: str, expected_version: Optional[int], new_owner: str
    ) -> bool:
        # If DB has true compare-and-swap, delegate
        if hasattr(self._db, "compare_and_update_worker_owner"):

            def _call():
                return self._db.compare_and_update_worker_owner(
                    worker_id, expected_version, new_owner
                )

            try:
                return DB_CB.call(_call)
            except Exception:
                logger.exception(
                    "compare_and_update_worker_owner failed via circuit breaker"
                )
                return False

        # If DB allows transaction, try to emulate CAS: read current and update if matches
        if hasattr(self._db, "execute_in_transaction"):

            def _tx(tx):
                # attempt to read using tx.get_worker_info or check_workers
                cur = None
                if hasattr(tx, "get_worker_info"):
                    cur = tx.get_worker_info(worker_id)
                elif hasattr(tx, "check_workers"):
                    # best-effort: not ideal
                    cur = None

                cur_ver = cur.get("version") if cur else None
                if cur_ver != expected_version:
                    return False
                # attempt update
                if hasattr(tx, "update_worker_owner"):
                    tx.update_worker_owner(worker_id, new_owner)
                    return True
                return False

            try:
                return DB_CB.call(self._db.execute_in_transaction, _tx)
            except Exception:
                logger.exception("CAS emulation failed")
                return False

        # otherwise we cannot safely CAS
        logger.warning(
            "CAS not supported by DatabaseService; compare_and_update_worker_owner unavailable"
        )
        return False

    def check_workers(
        self,
        stale_seconds: int = 300,
        max_restarts_per_hour: int = 3,
    ) -> dict:
        """Check worker health and return workers needing restart or quarantine.

        Returns a dict with 'restart' and 'quarantined' lists.
        """
        if hasattr(self._db, "check_workers"):

            def _call():
                return self._db.check_workers(
                    stale_seconds=stale_seconds,
                    max_restarts_per_hour=max_restarts_per_hour,
                )

            try:
                return DB_CB.call(_call)
            except Exception:
                logger.exception("check_workers failed via circuit breaker")
                return {"restart": [], "quarantined": []}

        # Fallback: return empty result if method not available
        logger.debug("check_workers not available on underlying DatabaseService")
        return {"restart": [], "quarantined": []}
