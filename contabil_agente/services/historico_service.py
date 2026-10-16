import datetime
import os
import sqlite3
import threading
import time
import logging
from typing import List, Tuple, Optional

# Blindagem de importação / fallback para configuração
try:
    from config.settings import DB_NAME as CONFIG_DB_NAME
except Exception:
    CONFIG_DB_NAME = None


DEFAULT_DB_PATH = (
    os.environ.get("DB_NAME")
    or CONFIG_DB_NAME
    or os.path.join("database", "historico_contabil.db")
)


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.datetime.fromtimestamp(record.created).isoformat()
        level = record.levelname
        op = getattr(record, "operation", "")
        msg = super().format(record)
        return f"[{ts}] [DB_SERVICE] [{level}] [{op}] - {msg}"


logger = logging.getLogger("DB_SERVICE")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(_StructuredFormatter("%(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


class HistoricoService:
    """Serviço para persistência do histórico de perguntas/respostas.

    Implementa:
    - Singleton com lazy init e lock
    - Hierarquia de descoberta do DB path
    - Garantia de diretório existente
    - Criação de tabela e índices críticos
    - Context managers para operações DB
    - Retries em caso de `database is locked`
    - Método de health check
    """

    _instance: Optional["HistoricoService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None, timeout: float = 5.0):
        # não chamar diretamente — use get_instance()
        self._init_lock = threading.Lock()
        self.db_path = db_path or DEFAULT_DB_PATH
        self.timeout = timeout
        self._ensure_db_dir()
        self._ensure_schema()

    @classmethod
    def get_instance(cls, *, db_path: Optional[str] = None) -> "HistoricoService":
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = HistoricoService(db_path=db_path)
            return cls._instance

    def _ensure_db_dir(self) -> None:
        d = os.path.dirname(self.db_path) or "."
        if d and not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
                logger.info("Criado diretório do DB", extra={"operation": "mkdir"})
            except Exception:
                logger.error(
                    "Falha ao criar diretório do DB", extra={"operation": "mkdir"}
                )
                raise

    def _connect(self):
        # sempre cria conexão por operação para evitar sharing entre threads
        return sqlite3.connect(self.db_path, timeout=self.timeout)

    def _ensure_schema(self) -> None:
        # Create table and indices if missing; idempotente
        create_sql = """
        CREATE TABLE IF NOT EXISTS historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj TEXT,
            pergunta TEXT,
            resposta TEXT,
            data TEXT
        )
        """

        idx_cmds = [
            # keep compatibility with existing columns
            "CREATE INDEX IF NOT EXISTS idx_historico_cnpj ON historico(cnpj)",
            "CREATE INDEX IF NOT EXISTS idx_historico_data ON historico(data)",
            # pergunta is used as proxy for tipo_documento (keeps schema compatibility)
            "CREATE INDEX IF NOT EXISTS idx_historico_pergunta ON historico(pergunta)",
        ]

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(create_sql)
                for cmd in idx_cmds:
                    cur.execute(cmd)
                conn.commit()
                logger.info(
                    "Schema verificado/criado", extra={"operation": "schema_init"}
                )
        except sqlite3.Error:
            logger.error(
                "Erro ao inicializar schema", extra={"operation": "schema_init"}
            )
            raise

    def _with_retry(
        self, fn, *args, max_retries: int = 3, backoff: float = 0.05, **kwargs
    ):
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as e:
                last_exc = e
                msg = str(e).lower()
                if "locked" in msg or "database is locked" in msg:
                    logger.warning("DB locked, retrying", extra={"operation": "retry"})
                    time.sleep(backoff * attempt)
                    continue
                else:
                    logger.exception(
                        "OperationalError inesperado", extra={"operation": "db_op"}
                    )
                    raise
            except sqlite3.Error:
                logger.exception(
                    "Erro sqlite durante operação", extra={"operation": "db_op"}
                )
                raise
        # se esgotou
        logger.error("Operação falhou após retries", extra={"operation": "retry"})
        raise last_exc

    def salvar_historico(self, cnpj: str, pergunta: str, resposta: str) -> None:
        """Persiste um registro no histórico.

        Usa contexto para garantir fechamento e retry se DB estiver locked.
        """

        def _op():
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO historico (cnpj, pergunta, resposta, data) VALUES (?, ?, ?, ?)",
                    (cnpj, pergunta, resposta, datetime.datetime.now().isoformat()),
                )
                conn.commit()

        try:
            with self._init_lock:
                self._with_retry(_op)
            logger.info("Registro salvo", extra={"operation": "salvar_historico"})
        except sqlite3.Error as e:
            logger.error(
                f"Falha ao salvar histórico: {e}",
                extra={"operation": "salvar_historico"},
            )

    def recuperar_historico(self, limit: int = 50) -> List[Tuple]:
        try:

            def _op():
                with self._connect() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT cnpj, pergunta, resposta, data
                        FROM historico
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                    return cur.fetchall()

            res = self._with_retry(_op)
            logger.info(
                "Recuperado histórico", extra={"operation": "recuperar_historico"}
            )
            return res or []
        except sqlite3.Error as e:
            logger.error(
                f"Erro ao recuperar histórico: {e}",
                extra={"operation": "recuperar_historico"},
            )
            return []

    def check_db_health(self) -> dict:
        """Verifica integridade básica do DB: existe, é gravável e legível."""
        status = {"ok": False, "path": self.db_path}
        try:
            # arquivo existe?
            if not os.path.exists(self.db_path):
                status.update({"ok": False, "reason": "not_found"})
                return status

            # try write/read a transaction
            test_key = f"health_{int(time.time())}"
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA integrity_check")
                integrity = cur.fetchone()
                if integrity and integrity[0] != "ok":
                    status.update(
                        {
                            "ok": False,
                            "reason": "integrity_failed",
                            "detail": integrity[0],
                        }
                    )
                    return status

                # lightweight write/read
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS __health_check (k TEXT PRIMARY KEY, v TEXT)"
                )
                cur.execute(
                    "INSERT OR REPLACE INTO __health_check (k, v) VALUES (?, ?)",
                    (test_key, "1"),
                )
                conn.commit()
                cur.execute("SELECT v FROM __health_check WHERE k = ?", (test_key,))
                if cur.fetchone() is None:
                    status.update({"ok": False, "reason": "rw_failed"})
                    return status

            status.update({"ok": True})
            return status
        except sqlite3.Error as e:
            logger.error(
                f"DB health check failed: {e}", extra={"operation": "health_check"}
            )
            status.update({"ok": False, "reason": str(e)})
            return status


# Backwards-compatible module-level API
_GLOBAL_SERVICE: Optional[HistoricoService] = None
_GLOBAL_LOCK = threading.Lock()


def _get_service(db_path: Optional[str] = None) -> HistoricoService:
    global _GLOBAL_SERVICE
    with _GLOBAL_LOCK:
        if _GLOBAL_SERVICE is None:
            _GLOBAL_SERVICE = HistoricoService.get_instance(db_path=db_path)
        return _GLOBAL_SERVICE


def salvar_historico(cnpj: str, pergunta: str, resposta: str) -> None:
    svc = _get_service()
    return svc.salvar_historico(cnpj, pergunta, resposta)


def recuperar_historico(limit: int = 50) -> List[Tuple]:
    svc = _get_service()
    return svc.recuperar_historico(limit=limit)


def check_db_health() -> dict:
    svc = _get_service()
    return svc.check_db_health()
