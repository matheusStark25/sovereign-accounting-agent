from __future__ import annotations

from typing import Any, Dict


class RedisAdapter:
    """Minimal Redis-like adapter for legal-hold and ephemeral state."""

    def __init__(self):
        self._store: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str):
        return self._store.get(key)

    def delete(self, key: str) -> None:
        if key in self._store:
            del self._store[key]

    # Simple list operations for reconciliation queue
    def lpush(self, key: str, value: Any) -> None:
        lst = self._store.get(key)
        if lst is None:
            lst = []
            self._store[key] = lst
        lst.insert(0, value)

    def rpop(self, key: str):
        lst = self._store.get(key)
        if not lst:
            return None
        return lst.pop()

    def llen(self, key: str) -> int:
        lst = self._store.get(key)
        if not lst:
            return 0
        return len(lst)
