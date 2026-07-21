"""Orquestrador central assíncrono para o Agente Contábil.

Fornece:
- TaskOrchestrator: filas (URGENTE / BATCH), retries, dead-letter queue
- CertificateManager: gerencia certificados A1/A3 (.pfx), valida expiração
- SnapshotManager: versionamento de mapeamentos UI e comparação via evidence
- Métodos de observabilidade: get_worker_metrics

Integra com `database_service.DatabaseService`, `audit_service` e `evidence_service`.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

# Dynamically import celery.schedules.crontab to avoid static import errors
# in environments where Celery is not installed (e.g. linting, type-check).
try:
    _cs = importlib.import_module("celery.schedules")
    crontab = getattr(_cs, "crontab")
except Exception:
    # Lightweight fallback so the module can be imported without Celery.
    def crontab(*args, **kwargs):
        return {"__stub_crontab__": True, "args": args, "kwargs": kwargs}


try:
    from infra.job_state import JobStateManager
except ImportError:
    from contabil_agente.infra.job_state import JobStateManager

try:
    from infra.worker import celery_app
except ImportError:
    from contabil_agente.infra.worker import celery_app

try:
    from contabil_agente.utils.logging_adapter import get_logger, set_correlation_id
except ImportError:
    from utils.logging_adapter import get_logger, set_correlation_id

try:
    from contabil_agente.services.integrity import verify_artifact_integrity
except ImportError:
    from services.integrity import verify_artifact_integrity

try:
    from contabil_agente.utils.outbox import TransactionalOutbox
except ImportError:
    from utils.outbox import TransactionalOutbox

try:
    from contabil_agente.utils.backoff import full_jitter_sleep
except ImportError:
    from utils.backoff import full_jitter_sleep

logger = get_logger("workflow_manager")

# Guarded imports
try:
    from contabil_agente.services.database_service import DatabaseService
except Exception:
    DatabaseService = None

try:
    from contabil_agente.services.audit_service import AuditService
except Exception:
    AuditService = None

try:
    from contabil_agente.services.evidence_service import EvidenceService
except Exception:
    EvidenceService = None

try:
    from contabil_agente.services.secret_manager import SecretManager
except Exception:
    SecretManager = None

# optional heavy deps
try:
    from cryptography.hazmat.primitives.serialization.pkcs12 import (
        load_key_and_certificates,
    )
    from cryptography.hazmat.backends import default_backend
    from cryptography import x509
except Exception:
    load_key_and_certificates = None
    x509 = None

try:
    from PIL import Image, ImageChops
except Exception:
    Image = None

# (imports for crontab, JobStateManager and celery_app are declared above)


@dataclass
class Task:
    id: Optional[int]
    task_type: str
    priority: str  # 'URGENTE' or 'BATCH'
    payload: Dict[str, Any]
    attempts: int = 0
    created_at: int = field(default_factory=lambda: int(time.time()))


class CertificateManager:
    """Gerencia certificados A1/A3 armazenados em `certs_dir`.

    Usa `SecretManager` para obter senhas por nome (env variable).
    """

    def __init__(
        self, certs_dir: Optional[str] = None, secret_manager: Optional[Any] = None
    ):
        self.certs_dir = certs_dir or os.path.join(
            os.path.dirname(__file__), "..", "certs"
        )
        os.makedirs(self.certs_dir, exist_ok=True)
        self.secret_manager = secret_manager or (
            SecretManager() if SecretManager else None
        )

    def list_certificates(self) -> List[str]:
        return [
            f
            for f in os.listdir(self.certs_dir)
            if f.lower().endswith((".pfx", ".p12"))
        ]

    def load_certificate(self, filename: str):
        path = os.path.join(self.certs_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        pwd = None
        if self.secret_manager:
            try:
                pwd = self.secret_manager.get(
                    f"CERT_PASS_{os.path.splitext(filename)[0]}"
                )
            except Exception:
                pwd = None
        with open(path, "rb") as fh:
            data = fh.read()
        if load_key_and_certificates:
            try:
                pk, cert, add = load_key_and_certificates(
                    data, pwd.encode() if pwd else None, backend=default_backend()
                )
                return cert
            except Exception as e:
                logger.debug("cryptography failed to load pfx: %s", e)
                return None
        # fallback: return raw bytes
        return data

    def validate_expiry(self, filename: str) -> Optional[Dict[str, Any]]:
        cert = self.load_certificate(filename)
        if cert is None:
            return None
        if hasattr(cert, "not_valid_after"):
            now = datetime.now(timezone.utc)
            days_left = (cert.not_valid_after - now).days
            if days_left < 30:
                msg = f"Cert {filename} expira em {days_left} dias"
                try:
                    if AuditService:
                        AuditService.get_instance().critical(msg)
                except Exception:
                    logger.critical(msg)
            return {"valid": now < cert.not_valid_after, "days_left": days_left}
        return None


class SnapshotManager:
    """Versionamento simples para mapeamentos UI (JSON files).

    Mantém pastas por sistema com arquivos `v{n}.json`.
    Comparação de snapshots baseada em evidence images (quando possível) ou hash simples.
    """

    def __init__(self, mappings_dir: Optional[str] = None):
        self.mappings_dir = mappings_dir or os.path.join(
            os.path.dirname(__file__), "..", "mappings"
        )
        os.makedirs(self.mappings_dir, exist_ok=True)

    def current_version(self, system: str) -> Optional[int]:
        d = os.path.join(self.mappings_dir, system)
        if not os.path.isdir(d):
            return None
        versions = []
        for f in os.listdir(d):
            if f.startswith("v") and f.endswith(".json"):
                try:
                    versions.append(int(f[1:-5]))
                except Exception:
                    continue
        return max(versions) if versions else None

    def load_mapping(
        self, system: str, version: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        d = os.path.join(self.mappings_dir, system)
        if not os.path.isdir(d):
            return None
        if version is None:
            version = self.current_version(system)
        if version is None:
            return None
        p = os.path.join(d, f"v{version}.json")
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def rollback_to(self, system: str, version: int) -> bool:
        # rollback is effectively selecting older mapping as current
        # systems consuming mapping should call load_mapping with that version
        self._audit(f"Rollback {system} to v{version}")
        return True

    def compare_snapshot(
        self, system: str, evidence_path: Optional[str] = None, threshold: float = 0.2
    ) -> bool:
        """Retorna True se mudança drástica detectada.

        Se PIL estiver disponível, faz diferença de imagens; senão compara hashes/sizes.
        """
        try:
            if Image and evidence_path and os.path.exists(evidence_path):
                # compare with baseline image if exists
                baseline = os.path.join(self.mappings_dir, system, "baseline.png")
                if not os.path.exists(baseline):
                    # create baseline if missing
                    shutil.copy2(evidence_path, baseline)
                    return False
                a = Image.open(baseline).convert("RGB")
                b = Image.open(evidence_path).convert("RGB")
                # resize to smallest
                if a.size != b.size:
                    b = b.resize(a.size)
                diff = ImageChops.difference(a, b)
                # diff histogram
                h = diff.histogram()
                # simple percent different pixels heuristic
                nonzero = sum(v for i, v in enumerate(h) if i % 256 != 0 or True)
                total = sum(h) or 1
                pct = nonzero / total
                return pct > threshold
            else:
                # fallback to filesize/hash
                baseline = os.path.join(self.mappings_dir, system, "baseline.hash")
                if not evidence_path or not os.path.exists(evidence_path):
                    return False
                with open(evidence_path, "rb") as fh:
                    data = fh.read()
                curhash = hashlib.sha256(data).hexdigest()
                if not os.path.exists(baseline):
                    with open(baseline, "w", encoding="utf-8") as fh:
                        fh.write(curhash)
                    return False
                with open(baseline, "r", encoding="utf-8") as fh:
                    old = fh.read().strip()
                return old != curhash
        except Exception as e:
            logger.debug("compare_snapshot failed: %s", e)
            return False

    def _audit(self, msg: str):
        try:
            if AuditService:
                AuditService.get_instance().log_operation(msg)
                return
        except Exception:
            pass
        logger.warning(msg)


class TaskOrchestrator:
    """Orquestra tarefas entre filas URGENTE e BATCH, gerencia retries, dead-letter e metrics.

    Integra com `DatabaseService` como source-of-truth para estados.
    """

    def __init__(self, db: Optional[Any] = None):
        # db may be an instance of DatabaseService; use Any in annotation to avoid
        # forward-reference issues when DatabaseService is conditionally imported
        self.db = db or (DatabaseService() if DatabaseService else None)
        # Transactional outbox helper
        self.outbox = TransactionalOutbox(self.db)
        self.urgent_q: asyncio.Queue[Task] = asyncio.Queue()
        self.batch_q: asyncio.Queue[Task] = asyncio.Queue()
        self.dead_letter: List[Task] = []
        self.workers: Dict[str, Dict[str, Any]] = {}
        self._pause_reasons: Set[str] = set()
        self._metrics_lock = threading.Lock()
        self._metrics: Dict[str, Dict[str, Any]] = {}
        self._stop = False

    def _audit(self, msg: str, level: str = "info"):
        try:
            if AuditService:
                AuditService.get_instance().log_operation(msg)
                return
        except Exception:
            pass
        getattr(logger, level)(msg)

    async def enqueue(self, task: Task) -> None:
        # persist in DB as queued
        try:
            self.outbox.send_with_outbox(
                task.payload.get("cnpj", ""), "queued", task.payload, event_name=None
            )
        except Exception:
            logger.debug("failed to persist queue record via outbox")

        if task.priority == "URGENTE":
            await self.urgent_q.put(task)
        else:
            await self.batch_q.put(task)
        self._audit(f"ENQUEUED {task.task_type} {task.payload.get('cnpj')}")

    async def get_next_task(self) -> Optional[Task]:
        # urgent preferred
        try:
            task = self.urgent_q.get_nowait()
            return task
        except asyncio.QueueEmpty:
            try:
                task = self.batch_q.get_nowait()
                return task
            except asyncio.QueueEmpty:
                return None

    def register_worker(
        self,
        name: str,
        handler: Callable[[Task], Awaitable[Any]],
        concurrency: int = 1,
        depends_on: Optional[List[str]] = None,
    ):
        self.workers[name] = {
            "handler": handler,
            "concurrency": concurrency,
            "tasks": 0,
            "success": 0,
            "failure": 0,
            "status": "idle",
            "depends_on": depends_on or [],
        }
        # spawn loops
        for i in range(concurrency):
            asyncio.create_task(self._worker_loop(name))

    async def _worker_loop(self, worker_name: str):
        info = self.workers[worker_name]
        handler = info["handler"]
        while not self._stop:
            # respect pause reasons
            if self._should_pause_worker(worker_name):
                info["status"] = "paused"
                await asyncio.sleep(2)
                continue
            task = await self._wait_for_task()
            if task is None:
                await asyncio.sleep(0.5)
                continue
            info["status"] = "running"
            start = time.time()
            try:
                task.attempts += 1
                res = await asyncio.wait_for(handler(task), timeout=600)
                elapsed = time.time() - start
                with self._metrics_lock:
                    m = self._metrics.setdefault(
                        worker_name, {"times": [], "success": 0, "failure": 0}
                    )
                    m["times"].append(elapsed)
                    m["success"] += 1
                info["success"] += 1
                info["status"] = "idle"
                # mark DB
                try:
                    self.outbox.send_with_outbox(
                        task.payload.get("cnpj", ""),
                        "done",
                        {"result": str(res)},
                        event_name=None,
                    )
                except Exception:
                    logger.debug("failed to persist done via outbox")
            except asyncio.TimeoutError:
                info["failure"] += 1
                with self._metrics_lock:
                    m = self._metrics.setdefault(
                        worker_name, {"times": [], "success": 0, "failure": 0}
                    )
                    m["failure"] += 1
                await self._handle_failure(task, "timeout")
            except Exception as e:
                info["failure"] += 1
                with self._metrics_lock:
                    m = self._metrics.setdefault(
                        worker_name, {"times": [], "success": 0, "failure": 0}
                    )
                    m["failure"] += 1
                await self._handle_failure(task, str(e))

    async def _wait_for_task(self, timeout: float = 1.0) -> Optional[Task]:
        # prefer urgent queue but wait across both
        try:
            task = await asyncio.wait_for(self.urgent_q.get(), timeout=timeout)
            return task
        except asyncio.TimeoutError:
            try:
                task = await asyncio.wait_for(self.batch_q.get(), timeout=timeout)
                return task
            except asyncio.TimeoutError:
                return None

    async def _handle_failure(self, task: Task, reason: str):
        task.attempts += 0  # already incremented
        self._audit(
            f"TASK_FAILURE {task.task_type} attempts={task.attempts} reason={reason}"
        )
        if task.attempts >= 3:
            self.dead_letter.append(task)
            self._audit(f"MOVED_TO_DEADLETTER {task.task_type} {task.payload}")
            try:
                self.outbox.send_with_outbox(
                    task.payload.get("cnpj", ""),
                    "dead_letter",
                    {"reason": reason},
                    event_name=None,
                )
            except Exception:
                logger.debug("failed to persist dead_letter via outbox")
            return
        # exponential backoff re-enqueue
        backoff = 2**task.attempts
        await asyncio.sleep(backoff)
        # re-enqueue with same priority
        if task.priority == "URGENTE":
            await self.urgent_q.put(task)
        else:
            await self.batch_q.put(task)

    def _should_pause_worker(self, worker_name: str) -> bool:
        # if paused reasons non-empty and worker depends_on any, pause
        if not self._pause_reasons:
            return False
        deps = self.workers[worker_name].get("depends_on", [])
        for r in self._pause_reasons:
            if r in deps:
                return True
        return False

    def cascade_pause(self, reason: str):
        self._pause_reasons.add(reason)
        self._audit(f"Cascade pause: {reason}")

    def cascade_resume(self, reason: str):
        if reason in self._pause_reasons:
            self._pause_reasons.remove(reason)
            self._audit(f"Cascade resume: {reason}")

    def get_worker_metrics(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        with self._metrics_lock:
            for name, info in self.workers.items():
                m = self._metrics.get(name, {"times": [], "success": 0, "failure": 0})
                times = m.get("times", [])
                avg = sum(times) / len(times) if times else 0.0
                out[name] = {
                    "avg_time": avg,
                    "success": m.get("success", 0),
                    "failure": m.get("failure", 0),
                    "status": info.get("status", "unknown"),
                    "concurrency": info.get("concurrency", 1),
                }
        return out


class Supervisor:
    """Background supervisor to monitor worker heartbeats and remediate stale workers.

    Uses DatabaseService.check_workers() to decide which workers need restart or
    should be quarantined. Callbacks can be registered per worker id to perform
    the actual restart action (e.g., restart a process or notify an orchestrator).
    """

    def __init__(
        self,
        db: Any,
        interval: int = 60,
        stale_seconds: int = 300,
        max_restarts_per_hour: int = 3,
    ):
        self.db = db
        self.interval = interval
        self.stale_seconds = stale_seconds
        self.max_restarts_per_hour = max_restarts_per_hour
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="WorkflowSupervisor", daemon=True
        )
        self._callbacks: Dict[str, Callable[[str], None]] = {}
        # Outbox helper if available
        try:
            from contabil_agente.utils.outbox import TransactionalOutbox

            self.outbox = TransactionalOutbox(self.db)
        except Exception:
            self.outbox = None

    def register_restart_callback(
        self, worker_id: str, callback: Callable[[str], None]
    ):
        self._callbacks[worker_id] = callback

    def start(self):
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self, timeout: int = 2):
        self._stop.set()
        try:
            self._thread.join(timeout=timeout)
        except Exception:
            pass

    def _loop(self):
        while not self._stop.is_set():
            try:
                result = self.db.check_workers(
                    stale_seconds=self.stale_seconds,
                    max_restarts_per_hour=self.max_restarts_per_hour,
                )
                to_restart = result.get("restart", []) or []
                quarantined = result.get("quarantined", []) or []

                for wid in to_restart:
                    cb = self._callbacks.get(wid)
                    attempt = 0
                    reassigned = False
                    while attempt < 3 and not reassigned:
                        attempt += 1
                        try:
                            # Strategy: optimistic locking via DB compare-and-swap APIs
                            if hasattr(self.db, "get_worker_info") and hasattr(
                                self.db, "compare_and_update_worker_owner"
                            ):
                                info = self.db.get_worker_info(wid)
                                cur_version = info.get("version") if info else None
                                # try to claim ownership for remediation
                                ok = self.db.compare_and_update_worker_owner(
                                    wid,
                                    expected_version=cur_version,
                                    new_owner="supervisor",
                                )
                                if ok:
                                    reassigned = True
                                    logger.info(
                                        "Supervisor: claimed worker %s for restart", wid
                                    )
                                    if cb:
                                        try:
                                            cb(wid)
                                        except Exception:
                                            logger.exception(
                                                "Restart callback for %s failed", wid
                                            )
                                    break
                            else:
                                # No CAS API: fallback to best-effort restart via callback
                                if cb:
                                    logger.info(
                                        "Supervisor: invoking restart callback for %s",
                                        wid,
                                    )
                                    try:
                                        cb(wid)
                                        reassigned = True
                                        break
                                    except Exception:
                                        logger.exception(
                                            "Restart callback for %s failed", wid
                                        )
                                else:
                                    try:
                                        self.db.notify_alert(
                                            f"Worker {wid} appears stale and requires restart"
                                        )
                                    except Exception:
                                        logger.exception(
                                            "notify_alert failed for %s", wid
                                        )
                                    break
                        except Exception:
                            logger.exception(
                                "Error handling restart attempt %s for %s", attempt, wid
                            )
                        # jittered backoff before retry
                        try:
                            import time as _t

                            _t.sleep(full_jitter_sleep(0.5, attempt))
                        except Exception:
                            pass

                    if not reassigned:
                        logger.critical(
                            "Supervisor: failed to reassign worker %s after attempts; moving to dead_letter",
                            wid,
                        )
                        try:
                            if self.outbox:
                                self.outbox.send_with_outbox(
                                    wid,
                                    "dead_letter",
                                    {
                                        "worker_id": wid,
                                        "reason": "stale_reassign_failed",
                                    },
                                    event_name="worker.dead_letter",
                                )
                            else:
                                # as fallback, try direct DB record
                                try:
                                    self.db.record_processamento(
                                        wid, "dead_letter", "stale_reassign_failed"
                                    )
                                except Exception:
                                    logger.exception(
                                        "failed to mark worker %s as dead_letter", wid
                                    )
                        except Exception:
                            logger.exception(
                                "failed to move worker %s to dead_letter via outbox",
                                wid,
                            )

                for wid in quarantined:
                    logger.critical(
                        "Supervisor: worker %s quarantined due to repeated failures",
                        wid,
                    )
                    try:
                        self.db.notify_alert(
                            f"Worker {wid} quarantined due to repeated failures"
                        )
                    except Exception:
                        logger.exception("notify_alert failed for quarantined %s", wid)
            except Exception:
                logger.exception("Supervisor loop error")

            # wait with early exit support
            self._stop.wait(self.interval)


@verify_artifact_integrity
async def example_extracao_handler(task: Task):
    """Exemplo de handler que chama integracao_gov.processar_empresa_unica.

    Nota: não reimplementa lógica do integracao_gov; apenas invoca.
    """
    try:
        from contabil_agente.tools.integracao_gov import processar_empresa_unica
    except Exception:
        raise RuntimeError("integracao_gov unavailable")
    # cria um browser/page previamente (assume caller provê em payload) or expect executor to manage
    page = task.payload.get("page")
    cnpj = task.payload.get("cnpj")
    modo = task.payload.get("modo", "best_effort")
    # If page is not provided, orchestrator should have created it — for example purpose, we error
    if page is None:
        raise RuntimeError("no_page_in_payload")
    res = await processar_empresa_unica(page, cnpj, modo)
    return res


__all__ = [
    "TaskOrchestrator",
    "Task",
    "CertificateManager",
    "SnapshotManager",
    "example_extracao_handler",
]
"""
Workflow Manager - Orquestrador de Rotinas Mensais
Agendamento automático de Folha, SPED, Vencimentos

Funcionalidades:
- Agendamento de rotinas mensais
- Execução automática em datas específicas
- Monitoramento de execução
- Integração com Celery Beat
"""


class WorkflowManager:
    """
    Gerenciador de Workflows e Rotinas Agendadas

    Rotinas Mensais:
    - Folha de Pagamento: Todo dia 5 de cada mês
    - SPED Contábil: Todo dia 10 de cada mês
    - Vencimentos: Diariamente às 06:00
    """

    def __init__(self):
        self.state_manager = JobStateManager()
        # Supervisor for monitoring worker heartbeats and automatic remediation
        try:
            from contabil_agente.services.database_adapter import DatabaseAdapter

            raw_db = DatabaseService() if DatabaseService else None
            self.db = DatabaseAdapter(raw_db) if raw_db else None
        except Exception:
            self.db = None
        try:
            self.supervisor = None
            if self.db:
                self.supervisor = Supervisor(self.db)
                self.supervisor.start()
        except Exception:
            logger.exception("Failed to start supervisor")

    def configurar_agendamentos(self) -> None:
        """
        Configura agendamentos periódicos no Celery Beat

        Esta função deve ser chamada na inicialização do worker
        para registrar as rotinas automáticas
        """
        # Atualiza configuração do Celery Beat
        celery_app.conf.beat_schedule.update(
            {
                # Folha de Pagamento - Todo dia 5 às 08:00
                "folha-mensal": {
                    "task": "infra.workflows.executar_folha_mensal",
                    "schedule": crontab(hour=8, minute=0, day_of_month=5),
                    "args": (),
                },
                # SPED Contábil - Todo dia 10 às 10:00
                "sped-mensal": {
                    "task": "infra.workflows.executar_sped_mensal",
                    "schedule": crontab(hour=10, minute=0, day_of_month=10),
                    "args": (),
                },
                # Vencimentos - Diariamente às 06:00
                "vencimentos-diarios": {
                    "task": "infra.workflows.processar_vencimentos_dia",
                    "schedule": crontab(hour=6, minute=0),
                    "args": (),
                },
                # Limpeza de jobs antigos - Todo domingo às 02:00
                "limpeza-jobs": {
                    "task": "infra.workflows.limpar_jobs_antigos",
                    "schedule": crontab(hour=2, minute=0, day_of_week=0),
                    "args": (),
                },
            }
        )

        logger.info("✅ Agendamentos configurados no Celery Beat")

    def agendar_workflow_customizado(
        self,
        workflow_name: str,
        task_name: str,
        schedule: Dict,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict] = None,
    ) -> bool:
        """
        Agenda workflow customizado

        Args:
            workflow_name: Nome único do workflow
            task_name: Nome da task a executar
            schedule: Definição de agendamento (crontab ou interval)
            args: Argumentos posicionais
            kwargs: Argumentos nomeados

        Returns:
            True se agendado com sucesso
        """
        try:
            celery_app.conf.beat_schedule[workflow_name] = {
                "task": task_name,
                "schedule": schedule,
                "args": args or (),
                "kwargs": kwargs or {},
            }

            logger.info(f"Workflow agendado: {workflow_name}")
            return True
        except Exception as e:
            logger.error(f"Erro ao agendar workflow: {e}")
            return False

    def executar_workflow_agora(
        self,
        task_name: str,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Executa workflow imediatamente (disparo manual)

        Args:
            task_name: Nome da task
            args: Argumentos posicionais
            kwargs: Argumentos nomeados
            user_id: ID do usuário que disparou

        Returns:
            Task ID
        """
        # Mapeamento de nomes lógicos para nomes completos das tasks (strings)
        task_name_map = {
            "processar_folha": "infra.tasks.processar_folha_pagamento",
            "gerar_sped": "infra.tasks.gerar_sped",
            "processar_vencimentos": "infra.tasks.processar_vencimentos",
        }

        target = task_name_map.get(task_name)
        if not target:
            raise ValueError(f"Task não encontrada: {task_name}")

        # Dispara a task via celery_app.send_task usando o nome (desacoplamento)
        result = celery_app.send_task(target, args=args or (), kwargs=kwargs or {})
        task_id = result.id

        # Cria estado inicial
        self.state_manager.create_job(
            task_id=task_id,
            task_name=task_name,
            user_id=user_id,
            metadata={
                "triggered_by": "manual",
                "args": str(args),
                "kwargs": str(kwargs),
            },
        )

        logger.info(f"Workflow disparado manualmente: {task_name} (ID: {task_id})")
        return task_id

    def listar_agendamentos_ativos(self) -> List[Dict]:
        """
        Lista todos os agendamentos ativos

        Returns:
            Lista de agendamentos com próxima execução
        """
        agendamentos = []

        for name, config in celery_app.conf.beat_schedule.items():
            agendamentos.append(
                {
                    "nome": name,
                    "task": config["task"],
                    "schedule": str(config["schedule"]),
                    "args": config.get("args", ()),
                    "kwargs": config.get("kwargs", {}),
                }
            )

        return agendamentos

    def pausar_agendamento(self, workflow_name: str) -> bool:
        """
        Pausa agendamento temporariamente
        Nota: Remove do beat_schedule (para reativar, precisa reconfigurar)
        """
        if workflow_name in celery_app.conf.beat_schedule:
            del celery_app.conf.beat_schedule[workflow_name]
            logger.info(f"Agendamento pausado: {workflow_name}")
            return True
        return False


# === WORKFLOWS AGENDADOS (Tasks) ===


@celery_app.task(name="infra.workflows.executar_folha_mensal")
def executar_folha_mensal() -> Dict:
    """
    Executa processamento de folha mensal para todas as empresas ativas
    Agendado para todo dia 5 às 08:00
    """
    set_correlation_id(None)
    logger.info("🗓️  Iniciando processamento de folha mensal automático")

    from infra.tasks import processar_folha_pagamento

    # Em produção, buscar empresas ativas do banco
    empresas_ativas = [
        {"id": "EMP001", "funcionarios": []},
        {"id": "EMP002", "funcionarios": []},
    ]

    mes_atual = datetime.now().month
    ano_atual = datetime.now().year

    resultados = []
    for empresa in empresas_ativas:
        # Dispara job de folha
        task = processar_folha_pagamento.apply_async(
            kwargs={
                "empresa_id": empresa["id"],
                "mes": mes_atual,
                "ano": ano_atual,
                "funcionarios": empresa["funcionarios"],
            }
        )

        resultados.append(
            {
                "empresa_id": empresa["id"],
                "task_id": task.id,
            }
        )

    return {
        "executado_em": datetime.now().isoformat(),
        "total_empresas": len(empresas_ativas),
        "tasks_disparadas": resultados,
    }


@celery_app.task(name="infra.workflows.executar_sped_mensal")
def executar_sped_mensal() -> Dict:
    """
    Gera SPED Contábil para todas as empresas
    Agendado para todo dia 10 às 10:00
    """
    set_correlation_id(None)
    logger.info("🗓️  Iniciando geração de SPED mensal automático")

    from infra.tasks import gerar_sped

    # Em produção, buscar empresas do banco
    empresas_ativas = ["EMP001", "EMP002"]

    # Período: mês anterior
    hoje = datetime.now()
    primeiro_dia_mes_anterior = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
    ultimo_dia_mes_anterior = hoje.replace(day=1) - timedelta(days=1)

    resultados = []
    for empresa_id in empresas_ativas:
        task = gerar_sped.apply_async(
            kwargs={
                "empresa_id": empresa_id,
                "tipo_sped": "CONTABIL",
                "periodo_inicio": primeiro_dia_mes_anterior.isoformat(),
                "periodo_fim": ultimo_dia_mes_anterior.isoformat(),
                "dados": {},  # Seria buscado do banco
            }
        )

        resultados.append(
            {
                "empresa_id": empresa_id,
                "task_id": task.id,
            }
        )

    return {
        "executado_em": datetime.now().isoformat(),
        "periodo": f"{primeiro_dia_mes_anterior.date()} a {ultimo_dia_mes_anterior.date()}",
        "tasks_disparadas": resultados,
    }


@celery_app.task(name="infra.workflows.processar_vencimentos_dia")
def processar_vencimentos_dia() -> Dict:
    """
    Processa vencimentos do dia
    Agendado para todo dia às 06:00
    """
    set_correlation_id(None)
    logger.info("🗓️  Processando vencimentos do dia")

    from infra.tasks import processar_vencimentos

    hoje = datetime.now().date().isoformat()

    task = processar_vencimentos.apply_async(kwargs={"data_referencia": hoje})

    return {
        "executado_em": datetime.now().isoformat(),
        "data_referencia": hoje,
        "task_id": task.id,
    }


@celery_app.task(name="infra.workflows.limpar_jobs_antigos")
def limpar_jobs_antigos() -> Dict:
    """
    Remove jobs antigos do Redis
    Agendado para todo domingo às 02:00
    """
    set_correlation_id(None)
    logger.info("🧹 Limpando jobs antigos")

    state_manager = JobStateManager()
    removidos = state_manager.cleanup_old_jobs(days=7)

    return {
        "executado_em": datetime.now().isoformat(),
        "jobs_removidos": removidos,
    }
