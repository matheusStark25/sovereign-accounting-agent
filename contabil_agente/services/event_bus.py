"""Event Bus minimal adapter (in-process async) with persistent event logfile.

Comunica via eventos; cada evento recebe `correlation_id` (UUID).
Persistência simples em `data/events/` para recuperação.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from contabil_agente.services.database_service import DatabaseService

_SUBSCRIBERS: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}


class AsyncEventBus:
    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir or os.path.join(
            os.path.dirname(__file__), "..", "data", "events"
        )
        os.makedirs(self.persist_dir, exist_ok=True)
        try:
            self.db = DatabaseService()
        except Exception:
            self.db = None

    def _persist_event(self, event: Dict[str, Any]) -> None:
        ts = int(time.time() * 1000)
        filename = f"{event['correlation_id']}.{ts}.json"
        path = os.path.join(self.persist_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(event, fh, ensure_ascii=False)
        except Exception:
            pass

    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cid = correlation_id or str(uuid.uuid4())
        event = {
            "correlation_id": cid,
            "type": event_type,
            "payload": payload,
            "timestamp": int(time.time()),
        }
        # persist to filesystem for resilience
        try:
            self._persist_event(event)
        except Exception:
            pass

        # publish to subscribers
        subs = list(_SUBSCRIBERS.get(event_type, []))
        for cb in subs:
            try:
                maybe = cb(event)
                if asyncio.iscoroutine(maybe):
                    asyncio.create_task(maybe)
            except Exception:
                # subscriber exceptions must not break bus
                continue

        return event

    def subscribe(
        self, event_type: str, callback: Callable[[Dict[str, Any]], Any]
    ) -> None:
        _SUBSCRIBERS.setdefault(event_type, []).append(callback)


# singleton
_BUS: Optional[AsyncEventBus] = None


def get_event_bus() -> AsyncEventBus:
    global _BUS
    if _BUS is None:
        _BUS = AsyncEventBus()
    return _BUS


# Lightweight in-process event bus functions (fast path)
# Uses existing asyncio import and typing definitions above.
#
_subscribers: Dict[str, List[Callable[[Any], Any]]] = {}


def subscribe(topic: str, handler: Callable[[Any], Any]) -> None:
    _subscribers.setdefault(topic, []).append(handler)


def unsubscribe(topic: str, handler: Callable[[Any], Any]) -> None:
    if topic in _subscribers and handler in _subscribers[topic]:
        _subscribers[topic].remove(handler)


async def publish(topic: str, message: Any) -> None:
    handlers = list(_subscribers.get(topic, []))
    for h in handlers:
        try:
            res = h(message)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            # swallow - event bus should not crash publishers
            continue


__all__ = ["subscribe", "unsubscribe", "publish"]
