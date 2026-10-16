"""Conversas guardadas em SQLite, sempre ligadas ao usuário e ao tenant que as criaram."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

RETENCAO_PADRAO_DIAS = 90  # alinhado a DataRetentionPolicy.POLICIES["chat_sessions"]


class ChatStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_sessions(user_id)")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path, timeout=10)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def nova_sessao(self, user_id: str, tenant_id: str) -> str:
        sid = uuid.uuid4().hex
        agora = time.time()
        with self._db() as con:
            con.execute(
                "INSERT INTO chat_sessions VALUES (?,?,?,?,?,?)", (sid, user_id, tenant_id, "{}", agora, agora)
            )
        return sid

    def carregar(self, session_id: str, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Estado da sessão, ou ``None`` se não existir ou pertencer a outro usuário/tenant."""
        with self._db() as con:
            linha = con.execute(
                "SELECT estado FROM chat_sessions WHERE id = ? AND user_id = ? AND tenant_id = ?",
                (session_id, user_id, tenant_id),
            ).fetchone()
        return None if linha is None else json.loads(linha[0])

    def salvar(self, session_id: str, user_id: str, tenant_id: str, estado: Dict[str, Any]) -> None:
        with self._db() as con:
            con.execute(
                "UPDATE chat_sessions SET estado = ?, updated_at = ? WHERE id = ? AND user_id = ? AND tenant_id = ?",
                (json.dumps(estado, ensure_ascii=False, default=str), time.time(), session_id, user_id, tenant_id),
            )

    def apagar_do_usuario(self, user_id: str) -> int:
        """Direito de exclusão (LGPD art. 18, VI): remove todas as conversas do usuário."""
        with self._db() as con:
            return con.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,)).rowcount

    def purgar_expiradas(self, dias: int = RETENCAO_PADRAO_DIAS) -> int:
        limite = time.time() - dias * 86400
        with self._db() as con:
            return con.execute("DELETE FROM chat_sessions WHERE updated_at < ?", (limite,)).rowcount
