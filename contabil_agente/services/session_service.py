"""
SessionService - Gerenciamento de sessões persistente com SQLite
Substitui o dicionário global em memória
"""

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SessionService:
    """
    Gerencia sessões de usuários de forma persistente
    Thread-safe e sobrevive a reinicializações do servidor
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = None):
        """Singleton pattern para garantir uma única instância"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: str = None):
        """Inicializa o serviço de sessões"""
        if not hasattr(self, "initialized"):
            self.db_path = db_path or "db/sessions.db"
            self._ensure_db_folder()
            # Thread-local storage for per-thread DB connections
            self._local = threading.local()
            # Lock to serialize writes for audit consistency
            self._db_lock = threading.Lock()
            self._init_database()
            self.initialized = True

    def _ensure_db_folder(self):
        """Garante que a pasta do banco existe"""
        Path(self.db_path).parent.mkdir(exist_ok=True, parents=True)

    def _init_database(self):
        """Cria a tabela de sessões se não existir"""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                messages TEXT NOT NULL,
                context TEXT NOT NULL,
                profile TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_activity REAL NOT NULL
            )
        """)

        # Índice para limpeza eficiente de sessões antigas
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_activity
            ON sessions(last_activity)
        """)

        conn.commit()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Recupera uma sessão pelo ID"""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT messages, context, profile, created_at, last_activity "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()

        if row:
            return {
                "messages": json.loads(row[0]),
                "contexto": json.loads(row[1]),
                "perfil": row[2],
                "created_at": row[3],
                "last_activity": row[4],
            }
        return None

    def create_session(
        self,
        session_id: str,
        messages: List[Dict] = None,
        context: Dict = None,
        profile: str = "neutro",
    ) -> Dict[str, Any]:
        """Cria uma nova sessão"""
        now = time.time()
        session_data = {
            "messages": messages or [],
            "contexto": context or {},
            "perfil": profile,
            "created_at": now,
            "last_activity": now,
        }

        conn = self._get_connection()
        with self._db_lock:
            conn.execute(
                "INSERT OR REPLACE INTO sessions "
                "(session_id, messages, context, profile, created_at, last_activity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    json.dumps(session_data["messages"], ensure_ascii=False),
                    json.dumps(session_data["contexto"], ensure_ascii=False),
                    profile,
                    now,
                    now,
                ),
            )
            conn.commit()

        logger.info(
            "session.created: %s profile=%s messages_count=%d",
            session_id,
            profile,
            len(session_data["messages"]),
        )

        return session_data

    def update_session(
        self,
        session_id: str,
        messages: List[Dict] = None,
        context: Dict = None,
        profile: str = None,
    ) -> bool:
        """Atualiza uma sessão existente"""
        session = self.get_session(session_id)
        if not session:
            return False

        # Atualizar apenas campos fornecidos
        if messages is not None:
            session["messages"] = messages
        if context is not None:
            session["contexto"].update(context)
        if profile is not None:
            session["perfil"] = profile

        session["last_activity"] = time.time()

        conn = self._get_connection()
        with self._db_lock:
            conn.execute(
                "UPDATE sessions SET "
                "messages = ?, context = ?, profile = ?, last_activity = ? "
                "WHERE session_id = ?",
                (
                    json.dumps(session["messages"], ensure_ascii=False),
                    json.dumps(session["contexto"], ensure_ascii=False),
                    session["perfil"],
                    session["last_activity"],
                    session_id,
                ),
            )
            conn.commit()

        # Auditoria: log ao criar/atualizar sessão
        logger.info(
            "session.updated: %s profile=%s messages_count=%d last_activity=%s",
            session_id,
            session["perfil"],
            len(session["messages"]),
            session["last_activity"],
        )

        return True

    def add_message(self, session_id: str, role: str, content: str) -> bool:
        """Adiciona uma mensagem ao histórico da sessão"""
        session = self.get_session(session_id)
        if not session:
            return False

        session["messages"].append({"role": role, "content": content})
        return self.update_session(session_id, messages=session["messages"])

    def delete_session(self, session_id: str) -> bool:
        """Remove uma sessão"""
        conn = self._get_connection()
        with self._db_lock:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("session.deleted: %s", session_id)
        return deleted

    def cleanup_old_sessions(self, max_age_seconds: int = 1800) -> int:
        """
        Remove sessões antigas (padrão: 30 minutos)
        Retorna quantidade de sessões removidas
        """
        cutoff_time = time.time() - max_age_seconds

        conn = self._get_connection()
        with self._db_lock:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE last_activity < ?", (cutoff_time,)
            )
            conn.commit()
            removed = cursor.rowcount

        if removed:
            logger.info("session.cleanup: removed=%d", removed)
        return removed

    def get_all_sessions(self) -> List[str]:
        """Lista todos os IDs de sessão ativos"""
        conn = self._get_connection()
        cursor = conn.execute("SELECT session_id FROM sessions")
        return [row[0] for row in cursor.fetchall()]

    def get_session_count(self) -> int:
        """Retorna quantidade total de sessões ativas"""
        conn = self._get_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM sessions")
        return cursor.fetchone()[0]

    def _get_connection(self) -> sqlite3.Connection:
        """Retorna uma conexão SQLite associada à thread atual.

        Mantemos uma conexão por thread (thread-local) para reduzir overhead
        de abrir/fechar conexões repetidamente, e configuramos o WAL para
        melhorar concorrência de leitura/gravação.
        """
        if not hasattr(self, "_local"):
            self._local = threading.local()

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            # Melhorar concorrência e segurança (journaling)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
            except Exception:
                # PRAGMA pode não funcionar em alguns ambientes; ignorar com log
                logger.debug("pragmas_not_applied", db_path=self.db_path)
            self._local.conn = conn

        return conn


# Singleton global para uso em toda aplicação
session_service = SessionService()
