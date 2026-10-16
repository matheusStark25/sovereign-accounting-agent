"""
Pool de conexões SQLite profissional
Gerencia conexões de forma thread-safe e eficiente
"""

import logging
import sqlite3
import threading
import atexit

from .config import Config

logger = logging.getLogger(__name__)


class DatabasePool:
    """Pool de conexões SQLite thread-safe"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, pool_size=10):
        if self._initialized:
            return

        self.pool_size = pool_size
        self.pool = []
        self.in_use = []
        self.lock = threading.Lock()

        # Inicializar conexões
        for _ in range(pool_size):
            conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self.pool.append(conn)

        self._initialized = True
        logger.info(f"DatabasePool inicializado com {pool_size} conexões")

    def get_connection(self):
        """Obtém uma conexão do pool"""
        with self.lock:
            if not self.pool:
                # Criar nova conexão se necessário
                conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                self.in_use.append(conn)
                return conn

            conn = self.pool.pop()
            self.in_use.append(conn)
            return conn

    def return_connection(self, conn):
        """Retorna uma conexão ao pool"""
        with self.lock:
            if conn in self.in_use:
                self.in_use.remove(conn)
                self.pool.append(conn)

    def close_all(self):
        """Fecha todas as conexões"""
        with self.lock:
            for conn in self.pool + self.in_use:
                try:
                    conn.close()
                except Exception:
                    pass
            self.pool.clear()
            self.in_use.clear()
        logger.info("DatabasePool fechado")


def _close_db_pool_on_exit():
    """Registrar fechamento ao término do processo para evitar ResourceWarning."""
    inst = DatabasePool._instance
    if inst is not None:
        try:
            inst.close_all()
        except Exception:
            logger.exception("Erro ao fechar DatabasePool on exit")


atexit.register(_close_db_pool_on_exit)


class TableCache:
    """Cache de tabelas em SQLite"""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._init_cache_table()

    def _init_cache_table(self):
        """Cria tabela de cache se não existir"""
        conn = self.db_pool.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cache_tabelas (
                    chave TEXT PRIMARY KEY,
                    valor TEXT,
                    expira_em TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            self.db_pool.return_connection(conn)

    def get(self, key):
        """Obtém valor do cache"""
        conn = self.db_pool.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT valor FROM cache_tabelas WHERE chave = ? AND expira_em > datetime('now')",
                (key,),
            )
            row = cur.fetchone()
            if row:
                import json

                return json.loads(row[0])
            return None
        finally:
            self.db_pool.return_connection(conn)

    def set(self, key, value, ttl=3600):
        """Define valor no cache"""
        import json
        from datetime import datetime, timedelta

        conn = self.db_pool.get_connection()
        try:
            cur = conn.cursor()
            expira_em = (datetime.now() + timedelta(seconds=ttl)).isoformat()
            cur.execute(
                """INSERT OR REPLACE INTO cache_tabelas (chave, valor, expira_em)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(value), expira_em),
            )
            conn.commit()
        finally:
            self.db_pool.return_connection(conn)
