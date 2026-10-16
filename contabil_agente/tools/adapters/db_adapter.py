from __future__ import annotations

from typing import Any, Dict, List


class DBAdapter:
    """Simple DB adapter scaffold. In production, implement ACID writes and cross-region replication."""

    def __init__(self):
        # In-memory store for demo/testing
        self._store: List[Dict[str, Any]] = []

    def write(self, record: Dict[str, Any]) -> None:
        # Should be transactional in real DB
        self._store.append(record.copy())

    def query_by_case(self, case_id: str) -> List[Dict[str, Any]]:
        return [r for r in self._store if r.get("case_id") == case_id]

    def dual_write(self, record: Dict[str, Any], secondary: "DBAdapter") -> None:
        # Write primary then secondary (dual-write pattern)
        self.write(record)
        # Best-effort write to secondary; real system would use durable queue + reconciliation
        secondary.write(record)
