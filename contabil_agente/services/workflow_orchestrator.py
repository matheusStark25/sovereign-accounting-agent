"""Orquestrador de Máquina de Estados persistente (EDA).

Gerencia documentos através de estados: CREATED -> TRIAGED -> PROCESSED -> DELIVERED
Usa o `event_bus` para comunicação e `DatabaseService.record_processamento` para checkpoints.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from contabil_agente.services.event_bus import get_event_bus
from contabil_agente.services.database_service import DatabaseService
from contabil_agente.utils.logging_adapter import get_logger, set_correlation_id

from contabil_agente.services.integrity import verify_artifact_integrity
from contabil_agente.utils.outbox import TransactionalOutbox
import os
import time

import asyncio
import inspect
import json
from typing import Callable

# Optional async dependencies (best-effort imports). If not available, fall back to no-op
try:
    import aiohttp
except Exception:  # pragma: no cover - optional
    aiohttp = None

try:
    import aioredis
except Exception:  # pragma: no cover - optional
    aioredis = None

try:
    from prometheus_client import Counter, Histogram
except Exception:  # pragma: no cover - optional
    Counter = Histogram = None

try:
    import asyncpg
except Exception:  # pragma: no cover - optional
    asyncpg = None

import functools

logger = get_logger("workflow_orchestrator")


# Structured JSON logger helper
def _log_json(level: str, msg: str, **fields: Any) -> None:
    payload = {"message": msg, "logger": "workflow_orchestrator", **fields}
    try:
        if level == "info":
            logger.info(json.dumps(payload))
        elif level == "warn":
            logger.warning(json.dumps(payload))
        elif level == "error":
            logger.error(json.dumps(payload))
        else:
            logger.debug(json.dumps(payload))
    except Exception:
        # fallback to non-structured logging
        logger.exception(msg)


# Simple async circuit breaker
class AsyncCircuitBreaker:
    def __init__(self, fail_max: int = 5, reset_timeout: int = 30):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.fail_count = 0
        self.opened_at: Optional[float] = None

    def _is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at > self.reset_timeout:
            # half-open: reset
            self.fail_count = 0
            self.opened_at = None
            return False
        return True

    async def call(self, func: Callable, *args, **kwargs):
        if self._is_open():
            raise RuntimeError("circuit_open")
        try:
            if inspect.iscoroutinefunction(func):
                res = await func(*args, **kwargs)
            else:
                res = await asyncio.to_thread(functools.partial(func, *args, **kwargs))
            # success
            self.fail_count = 0
            return res
        except Exception:
            self.fail_count += 1
            if self.fail_count >= self.fail_max:
                self.opened_at = time.time()
            raise


# Vault secret fetch helper (best-effort). Falls back to env var when Vault not reachable.
async def _fetch_secret_from_vault(path: str, key: str) -> Optional[str]:
    # path: secret path in Vault, key: field
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    if not vault_addr or not vault_token or aiohttp is None:
        return os.environ.get(key)
    url = f"{vault_addr}/v1/{path}"
    headers = {"X-Vault-Token": vault_token}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return os.environ.get(key)
                data = await resp.json()
                # support kv v2 and v1
                secret = data.get("data", {}).get("data", data.get("data", {}))
                return secret.get(key) if isinstance(secret, dict) else None
    except Exception:
        return os.environ.get(key)


# Prometheus metrics (best-effort stubs when prometheus_client missing)
if Counter and Histogram:
    METRIC_SUCCESS = Counter("orchestrator_success_total", "Successful orchestrations")
    METRIC_FAILURE = Counter("orchestrator_failure_total", "Failed orchestrations")
    METRIC_LATENCY = Histogram("orchestrator_latency_seconds", "Orchestrator latency")
else:

    class _Noop:
        def inc(self, *a, **k):
            pass

        def observe(self, *a, **k):
            pass

    METRIC_SUCCESS = METRIC_FAILURE = _Noop()
    METRIC_LATENCY = _Noop()

# Configurable infra parameters (can be overridden via env vars)
IDEMPOTENCY_TTL = int(os.environ.get("IDEMPOTENCY_TTL", "300"))  # seconds
PDF_CB_FAIL_MAX = int(os.environ.get("PDF_CB_FAIL_MAX", "3"))
PDF_CB_RESET_TIMEOUT = int(os.environ.get("PDF_CB_RESET_TIMEOUT", "60"))
SIG_CB_FAIL_MAX = int(os.environ.get("SIG_CB_FAIL_MAX", "3"))
SIG_CB_RESET_TIMEOUT = int(os.environ.get("SIG_CB_RESET_TIMEOUT", "60"))


class WorkflowOrchestrator:
    def __init__(self):
        self.bus = get_event_bus()
        try:
            from contabil_agente.services.database_adapter import DatabaseAdapter

            raw_db = DatabaseService()
            self.db = DatabaseAdapter(raw_db)
        except Exception:
            self.db = None
        # transactional outbox helper (best-effort)
        self.outbox = TransactionalOutbox(self.db, self.bus)
        # subscribe to created events
        self.bus.subscribe("document.created", self._on_document_created)
        # redis client lazy
        self._redis = None
        self._signature_cb = AsyncCircuitBreaker(fail_max=SIG_CB_FAIL_MAX, reset_timeout=SIG_CB_RESET_TIMEOUT)
        self._pdf_cb = AsyncCircuitBreaker(fail_max=PDF_CB_FAIL_MAX, reset_timeout=PDF_CB_RESET_TIMEOUT)

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            if aioredis is None:
                return None
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            self._redis = await aioredis.from_url(redis_url)
            return self._redis
        except Exception:
            return None

    @verify_artifact_integrity
    async def _on_document_created(self, event: Dict[str, Any]):
        cid = event.get("correlation_id")
        # correlation is set by decorator, but ensure it's propagated
        set_correlation_id(cid)
        payload = event.get("payload", {})
        # checkpoint + outbox publish in same transaction when possible
        try:
            self.outbox.send_with_outbox(
                cid, "CREATED", payload, event_name="document.triage_requested"
            )
        except Exception:
            logger.exception("failed to checkpoint+outbox CREATED %s", cid)

    @verify_artifact_integrity
    async def handle_triage_result(self, event: Dict[str, Any]):
        cid = event.get("correlation_id")
        set_correlation_id(cid)
        payload = event.get("payload", {})
        decision = payload.get("decision")
        # checkpoint + publish
        try:
            if decision == "UNCLASSIFIED":
                self.outbox.send_with_outbox(
                    cid, "TRIAGED", payload, event_name="document.await_human_review"
                )
                return
            domain = "dp.process" if decision == "DP" else "fiscal.process"
            self.outbox.send_with_outbox(cid, "TRIAGED", payload, event_name=domain)
        except Exception:
            logger.exception("failed to checkpoint+outbox TRIAGED %s", cid)

    @verify_artifact_integrity
    async def handle_processed(self, event: Dict[str, Any]):
        cid = event.get("correlation_id")
        set_correlation_id(cid)
        payload = event.get("payload", {})
        try:
            self.outbox.send_with_outbox(
                cid, "PROCESSED", payload, event_name="document.deliver"
            )
        except Exception:
            logger.exception("failed to checkpoint+outbox PROCESSED %s", cid)

    @verify_artifact_integrity
    async def handle_delivered(self, event: Dict[str, Any]):
        cid = event.get("correlation_id")
        set_correlation_id(cid)
        payload = event.get("payload", {})
        try:
            self.outbox.send_with_outbox(cid, "DELIVERED", payload, event_name=None)
        except Exception:
            logger.exception("failed to checkpoint+outbox DELIVERED %s", cid)


_ORCH: Optional[WorkflowOrchestrator] = None


def get_orchestrator() -> WorkflowOrchestrator:
    global _ORCH
    if _ORCH is None:
        _ORCH = WorkflowOrchestrator()
        # register callbacks for triage/processed/delivered events
        bus = get_event_bus()
        bus.subscribe("document.triage_result", _ORCH.handle_triage_result)
        bus.subscribe("document.processed", _ORCH.handle_processed)
        bus.subscribe("document.delivered", _ORCH.handle_delivered)
    return _ORCH


# NOTE: keep compatibility: expose a simple synchronous run() on the orchestrator


def _run_synchronous_orchestrator(dados: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility helper that creates a WorkflowOrchestrator and runs the
    end-to-end processing (calculo -> pdf -> assinatura) by delegating to
    the project's `AgenteContabil` implementation.

    Returns a dict with keys: success(bool), pdf_path(str|None), sha256(str|None),
    failed_step(str|None), error(str|None).
    """
    # Async-first orchestrator implemented with a synchronous compatibility wrapper
    async def _run_orchestrator_async(dados: Dict[str, Any]) -> Dict[str, Any]:
        start_ts = time.time()
        try:
            METRIC_LATENCY.observe(0) if hasattr(METRIC_LATENCY, "observe") else None
        except Exception:
            pass

        idempotency_key = dados.get("idempotency_key") or dados.get("request_id")
        # Idempotency check (Redis)
        redis = None
        try:
            try:
                orch = get_orchestrator()
                redis = await orch._get_redis()
            except Exception:
                redis = None
            if redis is None and aioredis is not None:
                try:
                    redis = await aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                except Exception:
                    redis = None

            if redis and idempotency_key:
                cached = await redis.get(f"idem:{idempotency_key}")
                if cached:
                    _log_json("info", "idempotency_hit", request_id=idempotency_key)
                    try:
                        return json.loads(cached)
                    except Exception:
                        return {"success": True, "cached": True}
        except Exception:
            pass

        _log_json("info", "orchestrator_start", request_id=idempotency_key)

        try:
            from contabil_agente.agent_contabil import AgenteContabil

            agent = AgenteContabil()

            # 1) Calcular (run in thread)
            _log_json("info", "step", step="calculo", request_id=idempotency_key)
            try:
                calc_result = await asyncio.to_thread(agent.calcular, dados)
                _log_json("info", "calculo_ok", request_id=idempotency_key)
            except Exception as e:
                METRIC_FAILURE.inc()
                _log_json("error", "calculo_failed", request_id=idempotency_key, error=str(e))
                return {"success": False, "failed_step": "calculo", "error": str(e)}

            # 2) Gerar PDF (via circuit breaker)
            _log_json("info", "step", step="pdf", request_id=idempotency_key)
            try:
                async def _pdf_call():
                    return await asyncio.to_thread(agent.gerar_pdf, calc_result, {"request_id": dados.get("request_id")})

                pdf_bytes, pdf_path = await get_orchestrator()._pdf_cb.call(_pdf_call)
                _log_json("info", "pdf_ok", request_id=idempotency_key, pdf_path=pdf_path)
            except Exception as e:
                METRIC_FAILURE.inc()
                _log_json("error", "pdf_failed", request_id=idempotency_key, error=str(e))
                return {"success": False, "failed_step": "pd", "error": str(e)}

            # persist PDF if needed (reuse existing logic)
            try:
                import importlib

                mod = importlib.import_module("contabil_agente.services.document_service")
                doc_svc = getattr(mod, "document_service", None)
            except Exception:
                doc_svc = None

            if not pdf_path or not str(pdf_path).strip():
                try:
                    timestamp = int(time.time())
                    safe_name = f"rescisao_{dados.get('request_id', 'req')[:8]}_{timestamp}.pdf"
                    if doc_svc and hasattr(doc_svc, "output_folder"):
                        out_folder = getattr(doc_svc, "output_folder")
                        os.makedirs(out_folder, exist_ok=True)
                        pdf_path = os.path.join(out_folder, safe_name)
                        with open(pdf_path, "wb") as f:
                            f.write(pdf_bytes or b"")
                    else:
                        base = os.path.dirname(os.path.dirname(__file__))
                        out_folder = os.path.join(base, "temp_docs")
                        os.makedirs(out_folder, exist_ok=True)
                        pdf_path = os.path.join(out_folder, safe_name)
                        with open(pdf_path, "wb") as f:
                            f.write(pdf_bytes or b"")
                except Exception as e:
                    METRIC_FAILURE.inc()
                    _log_json("error", "pdf_persist_failed", request_id=idempotency_key, error=str(e))
                    return {"success": False, "failed_step": "pd", "error": str(e)}
            else:
                try:
                    if doc_svc and hasattr(doc_svc, "output_folder"):
                        out_folder = getattr(doc_svc, "output_folder")
                        os.makedirs(out_folder, exist_ok=True)
                        target_name = os.path.basename(pdf_path)
                        target_path = os.path.join(out_folder, target_name)
                        if os.path.abspath(pdf_path) != os.path.abspath(target_path):
                            try:
                                with open(pdf_path, "rb") as src, open(target_path, "wb") as dst:
                                    dst.write(src.read())
                                pdf_path = target_path
                            except Exception:
                                pass
                except Exception:
                    pass

            # 3) Assinar / gerar hash (signature tool wrapped in circuit breaker)
            _log_json("info", "step", step="assinatura", request_id=idempotency_key)
            try:
                try:
                    from contabil_agente.services import signature_service

                    async def _signature_call(path):
                        return await asyncio.to_thread(signature_service.assinar_via_tool, path)

                    try:
                        svc_res = await get_orchestrator()._signature_cb.call(_signature_call, pdf_path)
                        _log_json("info", "signature_tool_resp", status=svc_res.get("status") if isinstance(svc_res, dict) else None)
                    except Exception as _e:
                        _log_json("warn", "signature_tool_unavailable", error=str(_e))
                except Exception:
                    pass

                data_bytes = None
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        data_bytes = f.read()
                else:
                    data_bytes = pdf_bytes or b""

                signature = await asyncio.to_thread(agent.sign_or_hash, data_bytes, pdf_path if pdf_path else None)
                sha = signature.get("sha256") if isinstance(signature, dict) else None
                _log_json("info", "assinatura_ok", request_id=idempotency_key, sha256=sha)
            except Exception as e:
                METRIC_FAILURE.inc()
                _log_json("error", "assinatura_failed", request_id=idempotency_key, error=str(e))
                return {"success": False, "failed_step": "assinatura", "error": str(e)}

            result = {"success": True, "pdf_path": pdf_path, "sha256": sha}

            # persist idempotency result
            try:
                if redis and idempotency_key:
                    await redis.set(f"idem:{idempotency_key}", json.dumps(result), ex=IDEMPOTENCY_TTL)
            except Exception:
                pass

            METRIC_SUCCESS.inc()
            elapsed = time.time() - start_ts
            try:
                METRIC_LATENCY.observe(elapsed)
            except Exception:
                pass
            _log_json("info", "orchestrator_end", request_id=idempotency_key, elapsed=elapsed)
            return result
        except Exception as e:
            # global error: attempt DLQ into Postgres
            METRIC_FAILURE.inc()
            _log_json("error", "orchestrator_critical_error", error=str(e), request_id=idempotency_key)
            try:
                dbsvc = DatabaseService()
                if hasattr(dbsvc, "record_critical_failure"):
                    await asyncio.to_thread(dbsvc.record_critical_failure, {"request": dados, "error": str(e)})
                else:
                    if asyncpg is not None:
                        pg_user = await _fetch_secret_from_vault("secret/data/postgres", "PG_USER") or os.environ.get("PG_USER")
                        pg_pass = await _fetch_secret_from_vault("secret/data/postgres", "PG_PASSWORD") or os.environ.get("PG_PASSWORD")
                        pg_db = await _fetch_secret_from_vault("secret/data/postgres", "PG_DB") or os.environ.get("PG_DB")
                        pg_host = await _fetch_secret_from_vault("secret/data/postgres", "PG_HOST") or os.environ.get("PG_HOST", "localhost")
                        conn_str = f"postgresql://{pg_user}:{pg_pass}@{pg_host}/{pg_db}"
                        conn = await asyncpg.connect(conn_str)
                        try:
                            await conn.execute(
                                "INSERT INTO falhas_criticas (request, error, created_at) VALUES ($1, $2, now())",
                                json.dumps(dados), str(e),
                            )
                        finally:
                            await conn.close()
            except Exception:
                _log_json("error", "dlq_failed", request_id=idempotency_key)

            return {"success": False, "failed_step": "orchestrator", "error": str(e)}

    # synchronous compatibility wrapper
    try:
        return asyncio.run(_run_orchestrator_async(dados))
    except Exception:
        import traceback

        traceback.print_exc()
        return {"success": False, "failed_step": "orchestrator", "error": "async_run_failed"}
