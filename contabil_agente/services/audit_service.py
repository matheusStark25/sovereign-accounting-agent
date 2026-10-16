"""
Audit Service - Sistema de Auditoria e Logs Estruturados
Rastreabilidade completa de operações críticas
"""

import logging
import os
import json
import queue
import threading
import time
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AuditService:
    """
    Serviço de auditoria para rastreamento de operações

    Funcionalidades:
    - Log estruturado de todas as operações financeiras
    - Rastreamento de usuário, tenant e timestamp
    - Suporte a níveis de severidade
    - Formato JSON para análise posterior
    """

    # Níveis de auditoria
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    # Categorias de operação
    CALCULO = "calculo"
    ACESSO_DADOS = "acesso_dados"
    MODIFICACAO = "modificacao"
    CONSULTA = "consulta"
    DOCUMENTO = "documento"

    # Lazy singleton
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, backend: Optional[str] = None, **kwargs):
        """Return singleton instance lazily. Accepts backend override and kwargs for configuration."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(backend=backend, **kwargs)
        return cls._instance

    def __init__(
        self,
        backend: Optional[str] = None,
        file_path: Optional[str] = None,
        db_config: Optional[Dict] = None,
        memory_only: bool = False,
        buffer_size: int = 2048,
        flush_interval: float = 0.1,
        cb_failure_threshold: int = 5,
    ):
        """Inicializa o serviço de auditoria.

        Args:
            backend: 'file'|'db'|'memory'|'null' or None to choose via ENV
            file_path: path for file backend
            db_config: dict with DB connection info (optional)
            memory_only: if True, do not touch filesystem
            buffer_size: max queued entries
            flush_interval: worker loop sleep / flush interval seconds
            cb_failure_threshold: consecutive backend failures before short-circuiting
        """
        # Respect global logging config: do not call basicConfig or add handlers here.
        self.logger = logging.getLogger(__name__)

        # Configuration hierarchy: param > ENV > default
        env_backend = os.getenv("AUDIT_BACKEND")
        self.backend_name = (backend or env_backend or "file").lower()
        self.file_path = file_path or os.getenv("AUDIT_FILE_PATH") or "audits.log"
        self.db_config = db_config or {}
        self.memory_only = bool(memory_only or os.getenv("AUDIT_MEMORY_ONLY") == "1")

        # Internal queue and worker
        self._queue = queue.Queue(maxsize=buffer_size)
        self._flush_interval = float(flush_interval)
        self._worker = None
        self._stop_event = threading.Event()

        # Circuit breaker config for backend failures
        self._cb_failure_threshold = int(cb_failure_threshold)
        self._cb_failures = 0
        self._cb_opened = False

        # Initialize backend lazily on first write
        self._backend = None
        self._backend_lock = threading.Lock()

        # Memory store for MemoryBackend when used or when backend fails
        self._memory_store = []

        # If memory_only requested, prefer memory backend
        if self.memory_only:
            self.backend_name = "memory"

    def log_operation(
        self,
        operation: str,
        category: str,
        user_id: str,
        tenant_id: str,
        details: Dict[str, Any],
        level: str = INFO,
        result: Optional[str] = "success",
    ) -> None:
        """
        Registra operação no log de auditoria

        Args:
            operation: Nome da operação (ex: 'calculo_rescisao')
            category: Categoria (CALCULO, ACESSO_DADOS, etc.)
            user_id: ID do usuário que executou
            tenant_id: ID do tenant
            details: Detalhes adicionais da operação
            level: Nível de severidade (INFO, WARNING, ERROR, CRITICAL)
            result: Resultado da operação ('success', 'error', 'partial')

        Exemplo:
            audit_service.log_operation(
                operation='calculo_rescisao',
                category=AuditService.CALCULO,
                user_id='usr_123',
                tenant_id='tenant_abc',
                details={
                    'salario_base': 3000.00,
                    'meses_trabalhados': 24,
                    'total_liquido': 8543.21
                },
                level=AuditService.INFO,
                result='success'
            )
        """
        # Build audit entry safely
        sanitized_details = self._sanitize_for_json(details)
        audit_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "category": category,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "details": sanitized_details,
            "level": level,
            "result": result,
        }

        # Non-blocking enqueue; if queue is full, drop oldest to preserve flow
        try:
            self._ensure_backend()
            self._queue.put_nowait(audit_entry)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()  # drop one
                self._queue.put_nowait(audit_entry)
                logger.warning(
                    json.dumps(
                        {"fallback": "audit_queue_full", "action": "dropped_oldest"}
                    )
                )
            except Exception:
                # last resort: append to in-memory store
                try:
                    self._memory_store.append(audit_entry)
                    logger.warning(
                        json.dumps(
                            {
                                "fallback": "audit_queue_and_drop_failed",
                                "action": "appended_memory",
                            }
                        )
                    )
                except Exception:
                    # Absolutely must not raise
                    logger.debug("audit drop: unable to enqueue or store audit entry")
        except Exception:
            logger.debug("audit enqueue error: %s", traceback.format_exc())

    def log_calculation(
        self,
        calc_type: str,
        user_id: str,
        tenant_id: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        success: bool = True,
    ) -> None:
        """
        Atalho para log de cálculos financeiros

        Args:
            calc_type: Tipo de cálculo (rescisao, ferias, folha_pagamento, etc.)
            user_id: ID do usuário
            tenant_id: ID do tenant
            inputs: Parâmetros de entrada
            outputs: Resultados calculados
            success: Se o cálculo foi bem-sucedido
        """
        details = {
            "tipo_calculo": calc_type,
            "inputs": inputs,
            "outputs": outputs,
            "timestamp_calculo": datetime.now(timezone.utc).isoformat(),
        }

        self.log_operation(
            operation=f"calculo_{calc_type}",
            category=self.CALCULO,
            user_id=user_id,
            tenant_id=tenant_id,
            details=details,
            level=self.INFO if success else self.ERROR,
            result="success" if success else "error",
        )

    def log_access(
        self,
        resource: str,
        resource_id: str,
        user_id: str,
        tenant_id: str,
        action: str = "read",
    ) -> None:
        """
        Log de acesso a recursos

        Args:
            resource: Tipo de recurso (funcionario, empresa, calculo, etc.)
            resource_id: ID do recurso acessado
            user_id: ID do usuário
            tenant_id: ID do tenant
            action: Ação realizada (read, write, delete)
        """
        details = {
            "resource_type": resource,
            "resource_id": resource_id,
            "action": action,
        }

        self.log_operation(
            operation=f"access_{resource}",
            category=self.ACESSO_DADOS,
            user_id=user_id,
            tenant_id=tenant_id,
            details=details,
            level=self.INFO,
        )

    def log_security_event(
        self,
        event_type: str,
        user_id: Optional[str],
        tenant_id: Optional[str],
        details: Dict[str, Any],
        severity: str = WARNING,
    ) -> None:
        """
        Log de eventos de segurança (tentativas de acesso, violações, etc.)

        Args:
            event_type: Tipo de evento (unauthorized_access, tenant_violation, etc.)
            user_id: ID do usuário (pode ser None se não autenticado)
            tenant_id: ID do tenant (pode ser None)
            details: Detalhes do evento
            severity: Severidade (WARNING, ERROR, CRITICAL)
        """
        security_details = {
            "event_type": event_type,
            "ip_address": details.get("ip_address", "unknown"),
            "user_agent": details.get("user_agent", "unknown"),
            **details,
        }

        self.log_operation(
            operation=f"security_{event_type}",
            category="security",
            user_id=user_id or "unauthenticated",
            tenant_id=tenant_id or "unknown",
            details=security_details,
            level=severity,
            result="security_event",
        )

    def _sanitize_for_json(self, data: Any) -> Any:
        """
        Sanitiza dados para serem serializáveis em JSON

        Converte Decimal para float, datetime para ISO string, etc.
        """
        if isinstance(data, dict):
            return {k: self._sanitize_for_json(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self._sanitize_for_json(item) for item in data]
        elif isinstance(data, Decimal):
            return float(data)
        elif isinstance(data, datetime):
            return data.isoformat()
        else:
            return data

    # --- Backend implementations (simple, resilient) ---
    class _BaseBackend:
        def write(self, entry: Dict[str, Any]):
            raise NotImplementedError()

    class _NullBackend(_BaseBackend):
        def write(self, entry: Dict[str, Any]):
            # no-op
            return True

    class _MemoryBackend(_BaseBackend):
        def __init__(self, store: list):
            self.store = store

        def write(self, entry: Dict[str, Any]):
            try:
                self.store.append(entry)
                return True
            except Exception:
                return False

    class _FileBackend(_BaseBackend):
        def __init__(self, path: str):
            self.path = path
            # open lazily per write to avoid persistent file descriptors

        def write(self, entry: Dict[str, Any]):
            try:
                # Ensure directory
                d = os.path.dirname(self.path)
                if d and not os.path.exists(d):
                    try:
                        os.makedirs(d)
                    except Exception:
                        pass
                line = json.dumps(entry, ensure_ascii=False)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return True
            except Exception:
                return False

    class _DBBackend(_BaseBackend):
        def __init__(self, config: Dict[str, Any]):
            self.config = config
            # Lightweight stub: real implementation should use connection pool

        def write(self, entry: Dict[str, Any]):
            try:
                # Placeholder: try to simulate DB write; in absence, just return False
                # Real implementation should handle connection, retries, timeouts
                return False
            except Exception:
                return False

    def _ensure_backend(self):
        """Instantiate backend lazily and start worker thread."""
        with self._backend_lock:
            if self._backend is not None:
                return

            if self.backend_name == "null":
                self._backend = self._NullBackend()
            elif self.backend_name == "memory":
                self._backend = self._MemoryBackend(self._memory_store)
            elif self.backend_name == "db":
                self._backend = self._DBBackend(self.db_config)
            else:
                # default file
                try:
                    self._backend = self._FileBackend(self.file_path)
                except Exception:
                    self._backend = self._MemoryBackend(self._memory_store)

            # Start worker thread
            if self._worker is None:
                self._worker = threading.Thread(target=self._worker_loop, daemon=True)
                self._worker.start()

    def _worker_loop(self):
        """Background worker that flushes queue to backend. Failure-tolerant."""
        while not self._stop_event.is_set():
            try:
                try:
                    entry = self._queue.get(timeout=self._flush_interval)
                except queue.Empty:
                    # periodic flush of memory_store if backend is file
                    entry = None

                if entry is not None:
                    success = False
                    try:
                        success = self._backend.write(entry)
                    except Exception:
                        success = False

                    if not success:
                        self._cb_failures += 1
                        logger.warning(
                            json.dumps(
                                {
                                    "audit_backend_failure": True,
                                    "failures": self._cb_failures,
                                }
                            )
                        )
                        if self._cb_failures >= self._cb_failure_threshold:
                            # circuit: switch to memory backend to avoid blocking
                            logger.warning(
                                json.dumps(
                                    {
                                        "audit_circuit": "opened",
                                        "action": "switching_to_memory",
                                    }
                                )
                            )
                            self._backend = self._MemoryBackend(self._memory_store)
                            # clear failure counter
                            self._cb_failures = 0
                    else:
                        # success -> reset failures
                        if self._cb_failures > 0:
                            self._cb_failures = 0

            except Exception:
                # Never let worker die
                logger.debug("audit worker error: %s", traceback.format_exc())
                time.sleep(0.5)

    def check_health(self) -> Dict[str, Any]:
        """Returns health info about audit service without raising."""
        backend = getattr(self._backend, "__class__", None)
        return {
            "backend": self.backend_name,
            "backend_impl": backend.__name__ if backend else None,
            "queue_size": self._queue.qsize() if hasattr(self, "_queue") else 0,
            "memory_store_len": len(self._memory_store),
            "circuit_open": self._cb_failures >= self._cb_failure_threshold,
        }


# No global instance at import time. Use `AuditService.get_instance()` to obtain the singleton lazily.

# Provide a module-level singleton for convenience when running the app
try:
    audit_service = AuditService.get_instance()
except Exception:
    # Ensure import-time errors don't break test discovery; lazy init fallback
    audit_service = None
