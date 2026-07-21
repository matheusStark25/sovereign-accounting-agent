from __future__ import annotations

import json
import logging
from typing import Any, Optional

try:
    from contabil_agente.services.event_bus import get_event_bus
except ImportError:
    from services.event_bus import get_event_bus

logger = logging.getLogger("contabil_agente.outbox")


class TransactionalOutbox:
    """Transactional Outbox helper.

    Tries to insert outbox_events in the same DB transaction as state changes.
    If the DatabaseService exposes a transaction context manager or
    `execute_in_transaction` callback, it will be used. Otherwise falls
    back to best-effort immediate publish.
    """

    def __init__(self, db: Optional[Any] = None, bus: Optional[Any] = None):
        self.db = db
        self.bus = bus or get_event_bus()

    def send_with_outbox(
        self,
        correlation_id: str,
        state: str,
        payload: Any,
        event_name: Optional[str] = None,
    ) -> None:
        body = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )
        if not self.db:
            # no DB available: immediate publish
            if event_name:
                try:
                    self.bus.publish(event_name, payload, correlation_id=correlation_id)
                except Exception:
                    logger.exception("outbox publish fallback failed")
            return

        try:
            # Preferred: DB provides transaction context manager
            if hasattr(self.db, "transaction"):
                with self.db.transaction():
                    self.db.record_processamento(correlation_id, state, body)
                    if event_name:
                        if hasattr(self.db, "insert_outbox_event"):
                            self.db.insert_outbox_event(
                                event_name, correlation_id, body
                            )
                        else:
                            # best-effort publish inside txn (not ideal)
                            self.bus.publish(
                                event_name, payload, correlation_id=correlation_id
                            )
                return

            if hasattr(self.db, "execute_in_transaction"):

                def _tx(tx):
                    self.db.record_processamento(correlation_id, state, body)
                    if event_name:
                        if hasattr(self.db, "insert_outbox_event"):
                            self.db.insert_outbox_event(
                                event_name, correlation_id, body
                            )
                        else:
                            self.bus.publish(
                                event_name, payload, correlation_id=correlation_id
                            )

                try:
                    self.db.execute_in_transaction(_tx)
                    return
                except Exception:
                    # fallthrough to best-effort
                    logger.exception("execute_in_transaction failed; falling back")

            # Fallback: write state then try to insert outbox or publish
            self.db.record_processamento(correlation_id, state, body)
            if event_name:
                if hasattr(self.db, "insert_outbox_event"):
                    try:
                        self.db.insert_outbox_event(event_name, correlation_id, body)
                    except Exception:
                        logger.exception(
                            "insert_outbox_event failed; publishing immediately"
                        )
                        try:
                            self.bus.publish(
                                event_name, payload, correlation_id=correlation_id
                            )
                        except Exception:
                            logger.exception("fallback publish failed")
                else:
                    try:
                        self.bus.publish(
                            event_name, payload, correlation_id=correlation_id
                        )
                    except Exception:
                        logger.exception("fallback publish failed")
        except Exception:
            logger.exception("Transactional outbox operation failed")
            # last-resort: immediate publish
            if event_name:
                try:
                    self.bus.publish(event_name, payload, correlation_id=correlation_id)
                except Exception:
                    logger.exception("final fallback publish failed")
