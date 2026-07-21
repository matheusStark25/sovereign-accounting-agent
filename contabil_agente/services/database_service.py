import os
import shutil
import sqlite3
import threading
import time
import gzip
import hashlib
import zipfile
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import json
import logging
import requests

import atexit
import weakref

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception

logger = logging.getLogger("database_service")

# Registry of live DatabaseService instances to ensure connections are closed on process exit
_DB_INSTANCE_REGISTRY = weakref.WeakSet()


def _close_all_db_instances():
    for inst in list(_DB_INSTANCE_REGISTRY):
        try:
            inst.close()
        except Exception:
            logger.debug(
                "Error closing DB instance during atexit cleanup", exc_info=True
            )


atexit.register(_close_all_db_instances)

# Ensure rotating file handler for persistent logs
try:
    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "contabil_agente.log")
    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        rh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
        )
        rh.setFormatter(formatter)
        logger.addHandler(rh)
except Exception:
    logger.debug("Failed to initialize rotating file handler", exc_info=True)

# Guarded import for AuditService
try:
    from contabil_agente.services.audit_service import AuditService
except Exception:
    AuditService = None


@dataclass
class Empresa:
    cnpj: str
    nome: Optional[str] = None
    regime: Optional[str] = None
    created_at: int = int(time.time())


@dataclass
class ProcessamentoLog:
    id: Optional[int]
    cnpj: str
    status: str
    message: Optional[str]
    timestamp: int = int(time.time())


@dataclass
class FinanceiroRecord:
    id: Optional[int]
    cnpj: str
    competencia: str
    valor: float
    status: str
    sha256: Optional[str]
    created_at: int = int(time.time())


class DatabaseService:
    """Resilient SQLite repository for contabil_agente.

    - WAL mode enabled
    - Thread-safe with threading.Lock
    - ACID transactions with automatic rollback
    - Schema versioning and basic migrations
    - Backup/restore and health checks
    """

    def __init__(
        self, db_path: Optional[str] = None, backups_dir: Optional[str] = None
    ):
        self.db_path = db_path or os.path.join(
            os.path.dirname(__file__), "..", "data", "contabil_agente.db"
        )
        # register instance for atexit/cleanup to avoid ResourceWarning unclosed DB
        try:
            _DB_INSTANCE_REGISTRY.add(self)
        except Exception:
            logger.debug("Failed to register DB instance for atexit", exc_info=True)
        self.db_path = os.path.abspath(self.db_path)
        self.backups_dir = backups_dir or os.path.join(
            os.path.dirname(self.db_path), "backups"
        )
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.backups_dir, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            self._conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            logger.debug("PRAGMA foreign_keys failed or unsupported", exc_info=True)
        self._conn.row_factory = sqlite3.Row

        # runtime-configurable behavior
        self._max_task_retries = int(os.getenv("TASK_MAX_RETRIES", "3"))
        # optional Fernet for secret encryption (set SECRET_ENCRYPTION_KEY env)
        self._fernet = None
        sk = os.getenv("SECRET_ENCRYPTION_KEY")
        if sk and Fernet is not None:
            try:
                if isinstance(sk, str):
                    skb = sk.encode()
                else:
                    skb = sk
                self._fernet = Fernet(skb)
            except Exception:
                logger.warning(
                    "Invalid SECRET_ENCRYPTION_KEY; secrets will be stored plaintext",
                    exc_info=True,
                )
        elif sk and Fernet is None:
            logger.warning(
                "cryptography not available; cannot enable secret encryption"
            )

        # initialize schema and migrations
        try:
            self._apply_migrations()
            self._ensure_indices()
        except Exception as e:
            logger.exception("Failed to initialize database: %s", e)
            # attempt to restore if integrity check fails
            try:
                if not self.health_check().get("integrity_ok", False):
                    logger.warning(
                        "Database integrity failed, attempting restore from backup"
                    )
                    self.restaurar_backup()
            except Exception:
                pass

    # ----- Utilities -----
    def _audit(self, msg: str, level: str = "info"):
        try:
            if AuditService:
                a = AuditService.get_instance()
                a.log_operation(msg)
                return
        except Exception:
            logger.debug("AuditService failed", exc_info=True)
        getattr(logger, level)(msg)

    def _transaction(self):
        class Tx:
            def __init__(self, svc: "DatabaseService"):
                self.svc = svc

            def __enter__(self):
                self.svc._lock.acquire()
                self.cursor = self.svc._conn.cursor()
                self.cursor.execute("BEGIN")
                return self.cursor

            def __exit__(self, exc_type, exc, tb):
                try:
                    if exc_type:
                        self.svc._conn.rollback()
                    else:
                        self.svc._conn.commit()
                finally:
                    try:
                        self.cursor.close()
                    except Exception:
                        logger.debug(
                            "Failed to close transaction cursor", exc_info=True
                        )
                    self.svc._lock.release()

        return Tx(self)

    # Public execute_in_transaction wrapper that accepts a callable
    def execute_in_transaction(self, fn):
        """Execute given callable inside DB transaction context and return its result."""
        # enter a transaction context; the callable may use the service instance
        # transaction cursor is available via service if needed
        with self._transaction():
            return fn(self)

    def close(self) -> None:
        """Close internal sqlite connection if open and unregister instance."""
        try:
            if getattr(self, "_conn", None):
                try:
                    self._conn.close()
                except Exception:
                    logger.debug("Error closing sqlite connection", exc_info=True)
                finally:
                    self._conn = None
        except Exception:
            logger.debug(
                "Unexpected error during DatabaseService.close()", exc_info=True
            )
        try:
            _DB_INSTANCE_REGISTRY.discard(self)
        except Exception:
            logger.debug("Failed to discard DB instance from registry", exc_info=True)

    def __del__(self):
        try:
            self.close()
        except Exception:
            logger.debug("Error in __del__ closing DB", exc_info=True)

    # ----- Schema / Migrations -----

    def _apply_migrations(self):
        with self._transaction() as cur:
            # Ensure schema_version table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at INTEGER NOT NULL
                )
                """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS empresas (
                    cnpj TEXT PRIMARY KEY,
                    nome TEXT,
                    regime TEXT,
                    created_at INTEGER
                )
                """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS processamentos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cnpj TEXT,
                    status TEXT,
                    message TEXT,
                    timestamp INTEGER
                )
                """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS financeiro (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cnpj TEXT,
                    competencia TEXT,
                    valor REAL,
                    status TEXT,
                    sha256 TEXT,
                    created_at INTEGER,
                    UNIQUE(cnpj, competencia)
                )
                """)

            # tasks table to act as persistent queue
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cnpj TEXT,
                    correlation_id TEXT,
                    owner_pid INTEGER,
                    started_at INTEGER,
                    payload TEXT,
                    priority TEXT,
                    state TEXT,
                    attempts INTEGER DEFAULT 0,
                    created_at INTEGER,
                    updated_at INTEGER
                )
                """)

            # secrets table to store encrypted secrets (optional)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS secrets (
                    name TEXT PRIMARY KEY,
                    value TEXT,
                    created_at INTEGER
                )
                """)
            # locks table for resource-level locking (granular semaphores)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS locks (
                    resource TEXT PRIMARY KEY,
                    owner TEXT,
                    expires_at INTEGER
                )
                """)
            # heartbeats for workers
            cur.execute("""
                CREATE TABLE IF NOT EXISTS heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    last_seen INTEGER,
                    restart_count INTEGER DEFAULT 0,
                    quarantined INTEGER DEFAULT 0
                )
                """)

            # set version if absent
            cur.execute("SELECT MAX(version) as v FROM schema_version")
            row = cur.fetchone()
            version = int(row["v"]) if row and row["v"] is not None else 0
            if version == 0:
                now = int(time.time())
                # classification decisions
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS classification_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        correlation_id TEXT,
                        classifier TEXT,
                        score REAL,
                        decision TEXT,
                        payload TEXT,
                        created_at INTEGER
                    )
                    """)

                # xml documents table for idempotency
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS xml_documents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sha256 TEXT UNIQUE,
                        content BLOB,
                        schema_ok INTEGER DEFAULT 0,
                        created_at INTEGER
                    )
                    """)
                # documents table for generic files (idempotency)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sha256 TEXT UNIQUE,
                        path TEXT,
                        metadata TEXT,
                        created_at INTEGER
                    )
                    """)

                # audit logs
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        level TEXT,
                        component TEXT,
                        message TEXT,
                        metadata TEXT,
                        created_at INTEGER
                    )
                    """)
                # outbox events for transactional outbox pattern
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS outbox_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_name TEXT,
                        correlation_id TEXT,
                        payload TEXT,
                        created_at INTEGER,
                        processed INTEGER DEFAULT 0
                    )
                    """)
                cur.execute(
                    "INSERT OR REPLACE INTO schema_version(version, applied_at) VALUES(?,?)",
                    (1, now),
                )
                self._audit("Applied initial schema version 1")

    def _ensure_indices(self):
        with self._transaction() as cur:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_financeiro_cnpj ON financeiro(cnpj)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_financeiro_competencia ON financeiro(competencia)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_cnpj ON tasks(cnpj)")

    # ----- CRUD methods -----
    def upsert_empresa(self, emp: Empresa) -> None:
        with self._transaction() as cur:
            cur.execute(
                "INSERT INTO empresas(cnpj,nome,regime,created_at) VALUES(?,?,?,?) ON CONFLICT(cnpj) DO UPDATE SET nome=excluded.nome, regime=excluded.regime",
                (emp.cnpj, emp.nome, emp.regime, emp.created_at),
            )
        self._audit(f"Empresa upserted {emp.cnpj}")

    # ----- Task queue methods -----
    def enqueue_task(
        self, cnpj: str, payload: Dict[str, any], priority: str = "BATCH"
    ) -> int:
        now = int(time.time())
        correlation_id = (
            payload.get("correlation_id") if isinstance(payload, dict) else None
        )
        # idempotency: if payload has orig_sha or sha, ensure not already ingested
        orig_sha = None
        if isinstance(payload, dict):
            orig_sha = payload.get("orig_sha") or payload.get("sha")
        if orig_sha and self.xml_exists_by_hash(orig_sha):
            self._audit(f"enqueue_task skipped duplicate sha={orig_sha}")
            return 0
        with self._transaction() as cur:
            cur.execute(
                "INSERT INTO tasks(cnpj,correlation_id,payload,priority,state,attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    cnpj,
                    correlation_id,
                    json.dumps(payload, ensure_ascii=False),
                    priority,
                    "PENDENTE",
                    0,
                    now,
                    now,
                ),
            )
            tid = cur.lastrowid
        self._audit(f"Task enqueued {tid} {cnpj} priority={priority}")
        return tid

    def claim_task(self, priority: Optional[str] = None) -> Optional[Dict[str, any]]:
        """Atomically claim one PENDENTE task and set to PROCESSANDO. Returns task dict or None."""
        with self._transaction() as cur:
            if priority:
                cur.execute(
                    "SELECT * FROM tasks WHERE state='PENDENTE' AND priority=? ORDER BY created_at LIMIT 1",
                    (priority,),
                )
            else:
                cur.execute(
                    "SELECT * FROM tasks WHERE state='PENDENTE' ORDER BY created_at LIMIT 1"
                )
            row = cur.fetchone()
            if not row:
                return None
            tid = row["id"]
            now = int(time.time())
            # set processing state and started_at
            cur.execute(
                "UPDATE tasks SET state=?, updated_at=?, started_at=? WHERE id=?",
                ("PROCESSANDO", now, now, tid),
            )
            return {k: row[k] for k in row.keys()}

    def complete_task(self, task_id: int) -> None:
        with self._transaction() as cur:
            now = int(time.time())
            cur.execute(
                "UPDATE tasks SET state=?, updated_at=? WHERE id=?",
                ("CONCLUIDO", now, task_id),
            )
        self._audit(f"Task {task_id} completed")

    def fail_task(self, task_id: int, reason: str) -> None:
        with self._transaction() as cur:
            cur.execute("SELECT attempts FROM tasks WHERE id=?", (task_id,))
            row = cur.fetchone()
            attempts = int(row["attempts"]) if row else 0
            attempts += 1
            now = int(time.time())
            if attempts >= getattr(self, "_max_task_retries", 3):
                cur.execute(
                    "UPDATE tasks SET state=?, attempts=?, updated_at=? WHERE id=?",
                    ("DEAD_LETTER", attempts, now, task_id),
                )
            else:
                cur.execute(
                    "UPDATE tasks SET state=?, attempts=?, updated_at=? WHERE id=?",
                    ("FALHA_RETRY", attempts, now, task_id),
                )
        self._audit(f"Task {task_id} failed attempt={attempts} reason={reason}")

    def record_processamento(
        self, cnpj: str, status: str, message: Optional[str] = None
    ) -> int:
        with self._transaction() as cur:
            cur.execute(
                "INSERT INTO processamentos(cnpj,status,message,timestamp) VALUES(?,?,?,?)",
                (cnpj, status, message, int(time.time())),
            )
            rid = cur.lastrowid
        self._audit(f"Processamento recorded {cnpj} #{rid} {status}")
        # create a backup snapshot after critical processing
        try:
            self.backup_db()
        except Exception:
            logger.debug("backup failed post processamento", exc_info=True)
        return rid

    def insert_financeiro(self, rec: FinanceiroRecord) -> int:
        with self._transaction() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO financeiro(cnpj,competencia,valor,status,sha256,created_at) VALUES(?,?,?,?,?,?)",
                (
                    rec.cnpj,
                    rec.competencia,
                    rec.valor,
                    rec.status,
                    rec.sha256,
                    rec.created_at,
                ),
            )
            rid = cur.lastrowid
        self._audit(f"Financeiro recorded {rec.cnpj} {rec.competencia} {rec.valor}")
        return rid

    def get_financeiro_history(
        self, cnpj: str, limit: int = 36
    ) -> List[FinanceiroRecord]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM financeiro WHERE cnpj=? ORDER BY created_at DESC LIMIT ?",
                (cnpj, limit),
            )
            rows = cur.fetchall()
            cur.close()
        out: List[FinanceiroRecord] = []
        for r in rows:
            out.append(
                FinanceiroRecord(
                    id=r["id"],
                    cnpj=r["cnpj"],
                    competencia=r["competencia"],
                    valor=float(r["valor"]),
                    status=r["status"],
                    sha256=r["sha256"],
                    created_at=int(r["created_at"]),
                )
            )
        return out

    # ----- Classification decisions -----
    def save_classification_decision(
        self,
        correlation_id: str,
        classifier: str,
        score: float,
        decision: str,
        payload: Dict[str, any],
    ) -> int:
        with self._transaction() as cur:
            cur.execute(
                "INSERT INTO classification_decisions(correlation_id,classifier,score,decision,payload,created_at) VALUES(?,?,?,?,?,?)",
                (
                    correlation_id,
                    classifier,
                    float(score),
                    decision,
                    json.dumps(payload, ensure_ascii=False),
                    int(time.time()),
                ),
            )
            cid = cur.lastrowid
        self._audit(
            f"Classification saved {cid} {correlation_id} {decision} score={score}"
        )
        return cid

    def get_classification_count(self) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(1) FROM classification_decisions")
            row = cur.fetchone()
            cur.close()
        return int(row[0]) if row and row[0] is not None else 0

    # ----- XML persistence & idempotency -----
    def xml_exists_by_hash(self, sha256hex: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT id FROM xml_documents WHERE sha256=?", (sha256hex,))
            row = cur.fetchone()
            cur.close()
        return bool(row)

    def save_xml_document(
        self, sha256hex: str, content: bytes, schema_ok: bool = False
    ) -> int:
        now = int(time.time())
        with self._transaction() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO xml_documents(sha256,content,schema_ok,created_at) VALUES(?,?,?,?)",
                (sha256hex, sqlite3.Binary(content), 1 if schema_ok else 0, now),
            )
            cur.execute("SELECT id FROM xml_documents WHERE sha256=?", (sha256hex,))
            row = cur.fetchone()
            docid = int(row[0]) if row else 0
        self._audit(f"XML saved id={docid} sha256={sha256hex} schema_ok={schema_ok}")
        return docid

    def save_document(
        self, sha256hex: str, path: str, metadata: Optional[Dict[str, any]] = None
    ) -> int:
        now = int(time.time())
        meta_text = json.dumps(metadata or {}, ensure_ascii=False)
        with self._transaction() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO documents(sha256,path,metadata,created_at) VALUES(?,?,?,?)",
                (sha256hex, path, meta_text, now),
            )
            cur.execute("SELECT id FROM documents WHERE sha256=?", (sha256hex,))
            row = cur.fetchone()
            docid = int(row[0]) if row else 0
        self._audit(f"Document saved id={docid} sha256={sha256hex} path={path}")
        return docid

    def document_exists(self, sha256hex: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT id FROM documents WHERE sha256=?", (sha256hex,))
            row = cur.fetchone()
            cur.close()
        return bool(row)

    def log_audit(
        self,
        level: str,
        component: str,
        message: str,
        metadata: Optional[Dict[str, any]] = None,
    ) -> int:
        now = int(time.time())
        meta_text = json.dumps(metadata or {}, ensure_ascii=False)
        with self._transaction() as cur:
            cur.execute(
                "INSERT INTO audit_logs(level,component,message,metadata,created_at) VALUES(?,?,?,?,?)",
                (level, component, message, meta_text, now),
            )
            aid = cur.lastrowid
        return aid

    # ----- Metrics helpers -----
    def get_dlq_size(self) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(1) FROM tasks WHERE state='DEAD_LETTER'")
            row = cur.fetchone()
            cur.close()
        return int(row[0]) if row and row[0] is not None else 0

    def get_tasks_total(self) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(1) FROM tasks")
            row = cur.fetchone()
            cur.close()
        return int(row[0]) if row and row[0] is not None else 0

    # ----- Secrets storage -----
    def save_secret(self, name: str, value: str) -> None:
        store_val = value
        if getattr(self, "_fernet", None):
            try:
                store_val = self._fernet.encrypt(value.encode()).decode()
            except Exception:
                logger.exception("Failed to encrypt secret; storing plaintext")

        with self._transaction() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO secrets(name,value,created_at) VALUES(?,?,?)",
                (name, store_val, int(time.time())),
            )
        if getattr(self, "_fernet", None) is None:
            logger.warning(
                "Secret stored in plaintext because SECRET_ENCRYPTION_KEY not configured"
            )
        self._audit(f"Secret saved {name}")

    def get_secret(self, name: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT value FROM secrets WHERE name=?", (name,))
            row = cur.fetchone()
            cur.close()
        if not row:
            return None
        val = row[0]
        if getattr(self, "_fernet", None) and val:
            try:
                return self._fernet.decrypt(val.encode()).decode()
            except InvalidToken:
                logger.error("Failed to decrypt secret: invalid token")
                return None
            except Exception:
                logger.exception("Failed to decrypt secret")
                return None
        return val

    # ----- Insights and Analytics -----
    def gerar_insight_gestao(
        self, cnpj: str, dados_atuais: Dict[str, any]
    ) -> Dict[str, any]:
        """Gera insights de gestão para o sócio virtual.

        dados_atuais: {'competencia': '2026-05', 'valor': 123.45, 'faturamento_mes': 1000.0}
        """
        history = self.get_financeiro_history(cnpj, limit=24)
        valores = [r.valor for r in history if r.valor is not None]
        insights: Dict[str, any] = {"cnpj": cnpj, "timestamp": int(time.time())}

        atual_valor = float(dados_atuais.get("valor", 0.0))
        insights["current_valor"] = atual_valor

        if valores:
            media = sum(valores) / len(valores)
            insights["historical_mean"] = media
            if media > 0 and abs(atual_valor - media) / media > 0.2:
                insights["alert_variation"] = {
                    "type": "desvio_percentual",
                    "mean": media,
                    "current": atual_valor,
                    "pct": (atual_valor - media) / media,
                }
        else:
            insights["historical_mean"] = None

        # Projeção de teto MEI (simple heuristic)
        try:
            faturamento_acumulado = float(
                dados_atuais.get("faturamento_acumulado", 0.0)
            )
            faturamento_mes = float(dados_atuais.get("faturamento_mes", 0.0))
            # project remaining months in year
            mes_atual = int(
                dados_atuais.get("mes_atual", datetime.now(timezone.utc).month)
            )
            meses_restantes = 12 - mes_atual
            projetado = faturamento_acumulado + faturamento_mes * meses_restantes
            insights["projection_annual"] = projetado
            MEI_LIMIT = float(dados_atuais.get("mei_limit", 81000.0))
            insights["mei_limit"] = MEI_LIMIT
            if projetado >= MEI_LIMIT:
                insights["alert_mei_risk"] = {
                    "projected": projetado,
                    "limit": MEI_LIMIT,
                    "message": "Risco de ultrapassar teto MEI",
                }
        except Exception:
            pass

        # Audit de pendencias: verifica se competencias anteriores aparecem como abertas
        try:
            competencia_atual = dados_atuais.get("competencia")
            if competencia_atual:
                abertas = [
                    r.competencia
                    for r in history
                    if getattr(r, "status", "")
                    and r.status.lower() in ("aberto", "pendente", "em aberto")
                ]
                if abertas:
                    insights["open_months_detected"] = list(set(abertas))
        except Exception:
            pass

        self._audit(f"INSIGHT {cnpj} {json.dumps(insights, ensure_ascii=False)}")
        return insights

    # ----- Backup / Restore / Maintenance -----
    def backup_db(self, dest_dir: Optional[str] = None) -> str:
        dest_dir = dest_dir or self.backups_dir
        os.makedirs(dest_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw = os.path.join(dest_dir, f"contabil_agente.db.{ts}.bak")
        archive = os.path.join(dest_dir, f"contabil_agente.db.{ts}.zip")
        # ensure all writes flushed
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self._conn.commit()
            shutil.copy2(self.db_path, raw)
        # compress
        try:
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(raw, arcname=os.path.basename(raw))
            os.remove(raw)
            try:
                os.chmod(archive, 0o600)
            except Exception:
                logger.debug(
                    "Could not set restrictive permissions on backup", exc_info=True
                )
            self._audit(f"DB_BACKUP_COMPRESSED {archive}")
            return archive
        except Exception:
            self._audit(f"DB_BACKUP_RAW {raw}")
            return raw

    def restore_and_validate(self, archive_path: str) -> bool:
        """Restore from a compressed backup and validate checksum/integrity."""
        if not os.path.exists(archive_path):
            raise FileNotFoundError(archive_path)
        tmp_restore = archive_path + ".restored"
        # extract
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                members = zf.namelist()
                if not members:
                    raise RuntimeError("Empty archive")
                member = members[0]
                zf.extract(member, os.path.dirname(tmp_restore))
                extracted = os.path.join(os.path.dirname(tmp_restore), member)
        except zipfile.BadZipFile:
            # maybe it's raw file
            extracted = archive_path

        # checksum
        h = hashlib.sha256()
        with open(extracted, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        checksum = h.hexdigest()

        # replace db and run integrity
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
            shutil.copy2(extracted, self.db_path)
            self._conn = sqlite3.connect(
                self.db_path, timeout=30, check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            row = cur.fetchone()
            cur.close()
        ok = row and row[0] == "ok"
        self._audit(
            f"DB_RESTORE_VALIDATE {archive_path} checksum={checksum} integrity_ok={ok}"
        )
        return bool(ok)

    def archive_old_completed(self, days: int = 90) -> int:
        cutoff = int(time.time()) - days * 24 * 3600
        with self._transaction() as cur:
            cur.execute(
                "SELECT id FROM tasks WHERE state='CONCLUIDO' AND updated_at<?",
                (cutoff,),
            )
            rows = cur.fetchall()
            ids = [r["id"] for r in rows]
            # move to archival table (simple export to file)
            if ids:
                archive_dir = os.path.join(os.path.dirname(self.db_path), "archives")
                os.makedirs(archive_dir, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                out = os.path.join(archive_dir, f"tasks_archived_{ts}.json.gz")
                cur2 = self._conn.cursor()
                cur2.execute(
                    f"SELECT * FROM tasks WHERE id IN ({','.join('?' for _ in ids)})",
                    ids,
                )
                allrows = [dict(r) for r in cur2.fetchall()]
                cur2.close()
                with gzip.open(out, "wt", encoding="utf-8") as gz:
                    json.dump(allrows, gz, ensure_ascii=False)
                cur.execute(
                    f"DELETE FROM tasks WHERE id IN ({','.join('?' for _ in ids)})", ids
                )
        self._audit(f"ARCHIVE_COMPLETED tasks={len(ids)}")
        return len(ids)

    def delete_old_evidence(
        self, evidence_dir: Optional[str] = None, days: int = 180
    ) -> int:
        evidence_dir = evidence_dir or os.path.join(
            os.path.dirname(self.db_path), "evidence"
        )
        if not os.path.isdir(evidence_dir):
            return 0
        cutoff = time.time() - days * 24 * 3600
        removed = 0
        for root, _, files in os.walk(evidence_dir):
            for f in files:
                p = os.path.join(root, f)
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.remove(p)
                        removed += 1
                except Exception:
                    continue
        self._audit(f"EVIDENCE_CLEANUP removed={removed}")
        return removed

    def restaurar_backup(self, backup_path: Optional[str] = None) -> bool:
        backups = sorted(
            [
                os.path.join(self.backups_dir, f)
                for f in os.listdir(self.backups_dir)
                if f.startswith("contabil_agente.db")
            ]
        )
        if backup_path is None:
            if not backups:
                raise FileNotFoundError("No backups available")
            backup_path = backups[-1]
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
            shutil.copy2(backup_path, self.db_path)
            self._conn = sqlite3.connect(
                self.db_path, timeout=30, check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.row_factory = sqlite3.Row
        self._audit(f"DB_RESTORE {backup_path}")
        return True

    def vacuum(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("VACUUM")
            cur.close()
        self._audit("DB_VACUUM")

    def health_check(self) -> Dict[str, any]:
        out: Dict[str, any] = {"ok": False, "integrity_ok": False}
        try:
            if not os.path.exists(self.db_path):
                out["reason"] = "missing_file"
                return out
            # quick query
            with self._lock:
                cur = self._conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                row = cur.fetchone()
                if row and row[0] == "ok":
                    out["integrity_ok"] = True
                cur.execute(
                    "SELECT COUNT(1) as c FROM sqlite_master WHERE type='table'"
                )
                r2 = cur.fetchone()
                out["tables"] = int(r2[0]) if r2 else 0
                cur.close()
            du = shutil.disk_usage(os.path.dirname(self.db_path))
            out["disk_free"] = du.free
            out["ok"] = True
        except Exception as e:
            out["error"] = str(e)
        self._audit(f"DB_HEALTH {json.dumps(out)}")
        return out

    # ----- Notifications / Alerts -----
    def notify_alert(self, message: str) -> None:
        """Send immediate alerts via configured webhooks (Telegram/Slack) and email if available."""
        try:
            telegram = os.getenv("TELEGRAM_WEBHOOK_URL")
            slack = os.getenv("SLACK_WEBHOOK_URL")
            if telegram:
                try:
                    requests.post(telegram, json={"text": message}, timeout=5)
                except Exception:
                    pass
            if slack:
                try:
                    requests.post(slack, json={"text": message}, timeout=5)
                except Exception:
                    pass
            # fallback email via DeliveryService if configured
            try:
                from contabil_agente.services.delivery_service import DeliveryService

                ds = DeliveryService()
                admin = os.getenv("ADMIN_ALERT_EMAIL")
                if admin:
                    ds.send_email(admin, "ALERT: contabil_agente", message)
            except Exception:
                # ignore delivery service failures, outer try will log if needed
                pass
        except Exception:
            logger.exception("notify_alert failed")

    # Integration helper for batch_manager checkpoint
    def get_checkpoint(self) -> Dict[str, Optional[str]]:
        """Return a lightweight checkpoint structure used by BatchManager."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT cnpj, competencia, created_at FROM financeiro ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return {"last_cnpj": None, "last_competencia": None}
        return {
            "last_cnpj": row[0],
            "last_competencia": row[1],
            "last_created_at": int(row[2]),
        }

    def get_last_processamento(self, identifier: str) -> Optional[Dict[str, any]]:
        """Return last processamento row for a given CNPJ (or identifier).

        Returns dict with keys: cnpj, status, message, timestamp
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM processamentos WHERE cnpj=? ORDER BY timestamp DESC LIMIT 1",
                (identifier,),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return None
        out = {k: row[k] for k in row.keys()}
        # try parse message JSON into meta
        try:
            out_meta = json.loads(out.get("message") or "{}")
            out["meta"] = out_meta
        except Exception:
            out["meta"] = None
        return out

    def get_processing_tasks(self, limit: int = 100) -> List[Dict[str, any]]:
        """Return tasks that are not finished (PENDENTE, PROCESSANDO, FALHA_RETRY) to allow resumption."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM tasks WHERE state IN ('PENDENTE','PROCESSANDO','FALHA_RETRY') ORDER BY created_at LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
        out: List[Dict[str, any]] = []
        for r in rows:
            out.append({k: r[k] for k in r.keys()})
        return out

    # ----- Transactional outbox helpers -----
    def insert_outbox_event(
        self, event_name: str, correlation_id: str, payload: str
    ) -> int:
        now = int(time.time())
        with self._transaction() as cur:
            cur.execute(
                "INSERT INTO outbox_events(event_name,correlation_id,payload,created_at,processed) VALUES(?,?,?,?,?)",
                (event_name, correlation_id, payload, now, 0),
            )
            eid = cur.lastrowid
        self._audit(f"Outbox event inserted {eid} {event_name} cid={correlation_id}")
        return eid

    def fetch_unprocessed_outbox(self, limit: int = 100) -> List[Dict[str, any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM outbox_events WHERE processed=0 ORDER BY created_at LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
        out = [{k: r[k] for k in r.keys()} for r in rows]
        return out

    def mark_outbox_processed(self, event_id: int) -> None:
        with self._transaction() as cur:
            cur.execute("UPDATE outbox_events SET processed=1 WHERE id=?", (event_id,))
        self._audit(f"Outbox event marked processed {event_id}")

    # ----- Worker CAS helpers -----
    def get_worker_info(self, worker_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT worker_id,last_seen,restart_count,quarantined FROM heartbeats WHERE worker_id=?",
                (worker_id,),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return None
        return {
            "worker_id": row["worker_id"],
            "last_seen": row["last_seen"],
            "restart_count": row["restart_count"],
            "quarantined": row["quarantined"],
            "version": int(row["restart_count"] or 0),
        }

    def compare_and_update_worker_owner(
        self, worker_id: str, expected_version: Optional[int], new_owner: str
    ) -> bool:
        """Attempt to update worker ownership/version atomically using transaction.

        Uses restart_count as a simple version counter for CAS emulation.
        """
        with self._transaction() as cur:
            cur.execute(
                "SELECT restart_count FROM heartbeats WHERE worker_id=?", (worker_id,)
            )
            row = cur.fetchone()
            cur_ver = int(row[0]) if row and row[0] is not None else 0
            if expected_version is not None and cur_ver != expected_version:
                return False
            # bump restart_count and set owner metadata in locks table as a coarse owner
            new_ver = cur_ver + 1
            cur.execute(
                "UPDATE heartbeats SET restart_count=? WHERE worker_id=?",
                (new_ver, worker_id),
            )
            # also update locks table as best-effort owner marker
            try:
                cur.execute(
                    "INSERT OR REPLACE INTO locks(resource,owner,expires_at) VALUES(?,?,?)",
                    (f"worker:{worker_id}", new_owner, int(time.time()) + 60),
                )
            except Exception:
                pass
        self._audit(
            f"compare_and_update_worker_owner {worker_id} -> {new_owner} ver={new_ver}"
        )
        return True

    def requeue_task(self, task_id: int) -> None:
        """Mark a task as PENDENTE again so it can be safely re-enqueued.

        This resets owner-related fields atomically to avoid duplicate workers
        processing the same task after a restart/resume.
        """
        now = int(time.time())
        with self._transaction() as cur:
            cur.execute(
                "UPDATE tasks SET state=?, owner_pid=NULL, started_at=NULL, updated_at=? WHERE id=?",
                ("PENDENTE", now, task_id),
            )
        self._audit(f"Task {task_id} requeued")

    # ----- Locking (resource-level) -----
    def acquire_lock(self, resource: str, owner: str, ttl_seconds: int = 60) -> bool:
        now = int(time.time())
        expires = now + ttl_seconds
        with self._transaction() as cur:
            # remove expired locks
            cur.execute("DELETE FROM locks WHERE expires_at<?", (now,))
            # try insert; if exists conflict, fail
            try:
                cur.execute(
                    "INSERT INTO locks(resource, owner, expires_at) VALUES(?,?,?)",
                    (resource, owner, expires),
                )
                return True
            except Exception:
                # already locked; consume result to keep cursor state consistent
                cur.execute(
                    "SELECT owner, expires_at FROM locks WHERE resource=?", (resource,)
                )
                cur.fetchone()
                return False

    def release_lock(self, resource: str, owner: str) -> bool:
        with self._transaction() as cur:
            cur.execute("SELECT owner FROM locks WHERE resource=?", (resource,))
            row = cur.fetchone()
            if not row:
                return True
            if row["owner"] != owner:
                return False
            cur.execute("DELETE FROM locks WHERE resource=?", (resource,))
            return True

    # ----- Heartbeat / Worker lifecycle -----
    def register_heartbeat(self, worker_id: str) -> None:
        now = int(time.time())
        with self._transaction() as cur:
            sql = (
                "INSERT OR REPLACE INTO heartbeats(worker_id, last_seen, restart_count, quarantined) "
                "VALUES(?, ?, COALESCE((SELECT restart_count FROM heartbeats WHERE worker_id=?), 0), "
                "COALESCE((SELECT quarantined FROM heartbeats WHERE worker_id=?), 0))"
            )
            cur.execute(sql, (worker_id, now, worker_id, worker_id))

    def check_workers(
        self, stale_seconds: int = 300, max_restarts_per_hour: int = 3
    ) -> Dict[str, any]:
        """Check heartbeats and return actions: restart list and quarantined list."""
        now = int(time.time())
        to_restart = []
        quarantined = []
        with self._transaction() as cur:
            cur.execute(
                "SELECT worker_id,last_seen,restart_count,quarantined FROM heartbeats"
            )
            rows = cur.fetchall()
            for r in rows:
                wid = r["worker_id"]
                last = int(r["last_seen"]) if r["last_seen"] else 0
                restarts = int(r["restart_count"]) if r["restart_count"] else 0
                q = int(r["quarantined"]) if r["quarantined"] else 0
                if q:
                    quarantined.append(wid)
                    continue
                if now - last > stale_seconds:
                    # calculate restarts window naive: allow max_restarts_per_hour resets per hour
                    if restarts >= max_restarts_per_hour:
                        cur.execute(
                            "UPDATE heartbeats SET quarantined=1 WHERE worker_id=?",
                            (wid,),
                        )
                        quarantined.append(wid)
                    else:
                        cur.execute(
                            "UPDATE heartbeats SET restart_count=restart_count+1 WHERE worker_id=?",
                            (wid,),
                        )
                        to_restart.append(wid)
        return {"restart": to_restart, "quarantined": quarantined}


__all__ = ["DatabaseService", "Empresa", "FinanceiroRecord", "ProcessamentoLog"]
