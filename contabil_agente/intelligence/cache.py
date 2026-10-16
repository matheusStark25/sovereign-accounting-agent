from __future__ import annotations

import sqlite3
import threading
import time
import json
import os
from typing import Any, Dict, Optional
import logging

try:
    from cryptography.fernet import Fernet

    _FERNET_AVAILABLE = True
except Exception:
    _FERNET_AVAILABLE = False

LOGGER = logging.getLogger("intelligence.cache")
DB_PATH = os.environ.get("INTELLIGENCE_CACHE_DB", "intelligence_cache.sqlite")


class CacheDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS entity_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at INTEGER,
                created_at INTEGER
            )
            """
            )
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS entity_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT,
                changed_at INTEGER,
                value TEXT
            )
            """
            )
            self._conn.commit()

    def set(self, key: str, value: Dict[str, Any], ttl_seconds: int = 3600):
        now = int(time.time())
        expires = now + ttl_seconds
        val = json.dumps(value, default=str)
        # optional encryption
        if _FERNET_AVAILABLE and os.environ.get("INTELLIGENCE_CACHE_KEY"):
            try:
                f = Fernet(os.environ.get("INTELLIGENCE_CACHE_KEY").encode())
                val = f.encrypt(val.encode()).decode()
            except Exception:
                LOGGER.exception("Failed to encrypt cache value; storing plaintext")
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "REPLACE INTO entity_cache(key, value, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (key, val, expires, now),
            )
            cur.execute(
                "INSERT INTO entity_history(key, changed_at, value) VALUES (?, ?, ?)",
                (key, now, val),
            )
            self._conn.commit()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT value, expires_at FROM entity_cache WHERE key = ?", (key,)
            )
            row = cur.fetchone()
            if not row:
                return None
            val, expires = row
            if expires and expires < now:
                # expired
                cur.execute("DELETE FROM entity_cache WHERE key = ?", (key,))
                self._conn.commit()
                return None
            try:
                # attempt decrypt if possible
                if _FERNET_AVAILABLE and os.environ.get("INTELLIGENCE_CACHE_KEY"):
                    try:
                        f = Fernet(os.environ.get("INTELLIGENCE_CACHE_KEY").encode())
                        val_dec = f.decrypt(val.encode()).decode()
                        return json.loads(val_dec)
                    except Exception:
                        # not encrypted or decrypt failed
                        pass
                return json.loads(val)
            except Exception:
                return None

    def history(self, key: str):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT changed_at, value FROM entity_history WHERE key = ? ORDER BY changed_at",
                (key,),
            )
            return [(r[0], json.loads(r[1])) for r in cur.fetchall()]

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
