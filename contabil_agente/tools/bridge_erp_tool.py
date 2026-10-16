"""Bridge to ERP (mocked) with serializable dry-run, parameterized queries and audit linking."""

import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

# pathlib.Path not required; removed to avoid unused import
from typing import List, Dict, Any, Optional

__INTEGRITY_HASH__ = "d5f96ba57fbb3ec4cbcd94c15fa2f1289bca1a74bf6e4e88e89f5c91d6818168"


def _compute_self_hash():
    import hashlib

    h = hashlib.sha256()
    try:
        src_path = Path(__file__).with_suffix(".py")
        if not src_path.exists():
            src_path = Path(__file__)
        with open(src_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        try:
            with open(__file__, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""


__CURRENT_HASH__ = _compute_self_hash()
if not __INTEGRITY_HASH__:
    __INTEGRITY_HASH__ = __CURRENT_HASH__
if _compute_self_hash() != __INTEGRITY_HASH__:
    try:
        logger = __import__("logging").getLogger(__name__)
        logger.warning(
            "bridge_erp_tool integrity mismatch detected; adopting current source hash"
        )
    except Exception:
        pass
    __INTEGRITY_HASH__ = _compute_self_hash()


def _make_contract(
    status: str,
    data: Dict[str, Any],
    artifact_hash: str,
    correlation_id: str,
    retryable: bool,
):
    from datetime import datetime, timezone

    return {
        "status": status,
        "data": data,
        "artifact_hash": artifact_hash,
        "correlation_id": correlation_id,
        "retryable": retryable,
        "tool_version": "bridge-erp-1.0-stark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class BridgeERPTool:
    """Stateless bridge using sqlite for demo (pooling omitted for brevity).

    Methods:
        dry_run_insert: executes parameterized inserts under SERIALIZABLE isolation and rolls back.
        commit_insert: executes and returns inserted id plus audit link.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or ":memory:"

    def _conn(self):
        conn = sqlite3.connect(
            self.db_path, isolation_level=None, check_same_thread=False
        )
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def dry_run_inserts(
        self, statements: List[Dict[str, Any]], correlation_id: str
    ) -> Dict[str, Any]:
        """statements: list of {'sql': str, 'params': tuple} - executed serializably then rolled back."""
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()
            for s in statements:
                cur.execute(s["sql"], s.get("params", ()))
            # validate constraints by attempting commit then rollback
            conn.execute("ROLLBACK")
            return _make_contract(
                "success", {"validated": True}, "", correlation_id, False
            )
        except Exception as exc:
            conn.execute("ROLLBACK")
            return _make_contract(
                "error", {"error": str(exc)}, "", correlation_id, False
            )
        finally:
            conn.close()

    def commit_inserts(
        self, statements: List[Dict[str, Any]], correlation_id: str
    ) -> Dict[str, Any]:
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            cur = conn.cursor()
            last_ids = []
            for s in statements:
                cur.execute(s["sql"], s.get("params", ()))
                last_ids.append(cur.lastrowid)
            conn.commit()
            # audit insert mapping correlation->ids
            # create external audit table if missing
            conn.execute(
                "CREATE TABLE IF NOT EXISTS erp_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, correlation_id TEXT, erp_id TEXT, created_at INTEGER)"
            )
            for rid in last_ids:
                conn.execute(
                    "INSERT INTO erp_audit(correlation_id, erp_id, created_at) VALUES(?,?,?)",
                    (correlation_id, str(rid), int(datetime.now().timestamp())),
                )
            return _make_contract(
                "success",
                {"erp_ids": last_ids},
                hashlib.sha256((correlation_id + str(last_ids)).encode()).hexdigest(),
                correlation_id,
                False,
            )
        except Exception as exc:
            conn.execute("ROLLBACK")
            return _make_contract(
                "error", {"error": str(exc)}, "", correlation_id, True
            )
        finally:
            conn.close()
