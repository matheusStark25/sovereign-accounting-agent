from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from decimal import Decimal, localcontext
from typing import Any, Dict, List, Optional

from contabil_agente.tools.adapters.kms_adapter import KMSAdapter
from contabil_agente.tools.adapters.db_adapter import DBAdapter
from contabil_agente.tools.adapters.redis_adapter import RedisAdapter
from contabil_agente.tools.adapters.idp_adapter import IDPAdapter

try:
    # Import opentelemetry dynamically to avoid hard dependency at static-analysis time
    import importlib

    _ot = importlib.import_module("opentelemetry")
    # prefer the trace submodule if available
    trace = getattr(_ot, "trace", _ot)
except Exception:
    # Fallback noop tracer when opentelemetry isn't installed
    class _NoopTracer:
        @contextmanager
        def start_as_current_span(self, *a, **k):
            yield None

    trace = _NoopTracer()


# Try to import prometheus_client dynamically; fallback to dummy classes if not available
try:
    import importlib

    _prom = importlib.import_module("prometheus_client")
    Counter = getattr(_prom, "Counter")
    Gauge = getattr(_prom, "Gauge")
except Exception:
    # If prometheus_client isn't installed or can't be imported, provide no-op standins.
    class Counter:
        def __init__(self, *args, **kwargs):
            pass

        def inc(self, *args, **kwargs):
            pass

    class Gauge:
        def __init__(self, *args, **kwargs):
            pass

        def set(self, *args, **kwargs):
            pass


logger = logging.getLogger("sovereign_tool")


# Try to import base class; prefer relative import (works in-package),
# fallback to absolute import, and finally provide a minimal stand-in.
try:
    # Preferred: relative import when used as a package
    from .base import BaseSovereignTool  # type: ignore
except Exception:
    try:
        # Fallback to absolute import (useful for some execution contexts)
        from contabil_agente.tools.base import BaseSovereignTool  # type: ignore
    except Exception:
        # Minimal fallback implementation so the module remains usable
        class BaseSovereignTool:
            def __init__(self, *args, **kwargs):
                pass


@dataclass(frozen=True)
class CalculationData:
    tenant_id: str
    total: Decimal
    taxes: Decimal
    items_count: int


@dataclass
class SovereignToolManifest:
    name: str
    version: str
    author: str
    description: str
    created_at: str


class CircuitBreaker:
    def __init__(self, fail_threshold: int = 5, reset_timeout: int = 30):
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self._fail_count = 0
        self._last_failure = 0
        self._state_lock = threading.Lock()

    def call_allowed(self) -> bool:
        with self._state_lock:
            if self._fail_count >= self.fail_threshold:
                if time.time() - self._last_failure > self.reset_timeout:
                    self._fail_count = 0
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._state_lock:
            self._fail_count = 0

    def record_failure(self) -> None:
        with self._state_lock:
            self._fail_count += 1
            self._last_failure = time.time()


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self._last = time.time()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        with self._lock:
            now = time.time()
            delta = now - self._last
            self.tokens = min(self.capacity, self.tokens + delta * self.refill_rate)
            self._last = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


def mask_pii(text: str) -> str:
    # Simple regex-based PII masking (emails, CPF-like, phone). Expand as needed.
    if not text:
        return text
    text = re.sub(r"[\w\.-]+@[\w\.-]+", "[REDACTED_EMAIL]", text)
    text = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", "[REDACTED_CPF]", text)
    text = re.sub(r"\b\+?\d[\d\s\-()]{7,}\b", "[REDACTED_PHONE]", text)
    return text


def sanitize_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Remove suspicious patterns to defend against SQLi / XSS / path traversal
    sanitized = {}
    blacklist = [r"\b(SELECT|INSERT|UPDATE|DELETE|DROP)\b", r"<script", r"\.\./"]
    for k, v in payload.items():
        if isinstance(v, str):
            s = v
            for p in blacklist:
                s = re.sub(p, "", s, flags=re.IGNORECASE)
            sanitized[k] = s
        else:
            sanitized[k] = v
    return sanitized


# adapter imports moved to top of file to satisfy linter (imports must be at module top)


class SovereignCalculationTool(BaseSovereignTool):
    __version__ = "1.0.0"

    def __init__(
        self,
        *,
        hard_deps: Dict[str, Any],
        soft_deps: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        # Hard deps: db_primary, db_secondary, kms, redis
        # Accept both named and legacy keys for flexibility
        self.db_primary: DBAdapter = hard_deps.get("db_primary") or hard_deps.get("db")
        self.db_secondary: Optional[DBAdapter] = hard_deps.get("db_secondary")
        self.kms: KMSAdapter = hard_deps.get("kms")
        self.redis: RedisAdapter = hard_deps.get("redis")
        self.idp: Optional[IDPAdapter] = hard_deps.get("idp")

        # Soft deps: telemetry, logger
        self.telemetry = (soft_deps or {}).get("telemetry")

        # Config
        cfg = config or {}
        self.payload_size_limit = int(cfg.get("payload_size_limit", 1024 * 1024))
        self.recursion_depth_limit = int(cfg.get("recursion_depth_limit", 50))
        self.bulkhead_limit = int(cfg.get("bulkhead_limit", 10))
        self.circuit_breaker = CircuitBreaker(
            fail_threshold=cfg.get("cb_fail_threshold", 5),
            reset_timeout=cfg.get("cb_reset_timeout", 30),
        )
        self.rate_limiter = TokenBucket(
            capacity=cfg.get("rate_capacity", 100),
            refill_rate=cfg.get("rate_refill", 10),
        )

        # Bulkhead semaphore
        self._bulkhead = threading.BoundedSemaphore(self.bulkhead_limit)

        # Metrics
        self._metric_calls = Counter(
            "sovereign_tool_calls_total", "Total calls to sovereign tool"
        )
        self._metric_processing_ms = Gauge(
            "sovereign_tool_processing_ms", "Processing time ms"
        )

        # Manifest
        self.manifest = SovereignToolManifest(
            name="SovereignCalculationTool",
            version=self.__version__,
            author="autogen",
            description="High-assurance sovereign calculation tool",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        # Legal hold index namespace in redis
        self._legal_hold_prefix = "legal_hold:"

    # Lifecycle hooks
    def _setup(self) -> None:
        # Validate critical hard dependencies
        if not getattr(self, "db_primary", None):
            raise RuntimeError("DB primary dependency required")
        if not getattr(self, "kms", None):
            raise RuntimeError("KMS dependency required")
        # warm caches or connections
        try:
            if getattr(self, "db_primary", None) and hasattr(self.db_primary, "ping"):
                self.db_primary.ping()
        except Exception:
            logger.warning("DB ping failed during setup")

    def _validate_schema(self, payload: Dict[str, Any]) -> None:
        # Minimal but strict schema validation
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if "tenant_id" not in payload:
            raise ValueError("tenant_id is required")
        if "items" not in payload or not isinstance(payload["items"], list):
            raise ValueError("items must be a list")

    def _teardown(self) -> None:
        # flush transient state if needed
        try:
            if hasattr(self.redis, "flush"):
                pass
        except Exception:
            logger.debug("teardown: redis flush not available")

    # Dual-write and replication scaffold
    def _dual_write(self, record: Dict[str, Any]) -> None:
        # Write to primary; attempt secondary if configured
        if not self.db_primary:
            logger.error("no primary DB configured for dual write")
            return
        try:
            if self.db_secondary:
                self.db_primary.dual_write(record, self.db_secondary)
            else:
                self.db_primary.write(record)
        except Exception:
            # In production push to durable queue and schedule reconciliation
            logger.exception("dual-write failed; queued for reconciliation")
            try:
                self._enqueue_reconciliation(record)
            except Exception:
                logger.exception("failed to enqueue reconciliation record")

    def _enqueue_reconciliation(self, record: Dict[str, Any]) -> None:
        # Serialize and push to a reconciliation queue (resilient store like Redis)
        if not self.redis:
            logger.error("no redis configured; cannot enqueue reconciliation")
            return
        key = "reconcile_queue"
        payload = json.dumps({"ts": time.time(), "record": record}, sort_keys=True)
        # push to queue
        self.redis.lpush(key, payload)

    def reconcile_dual_writes(
        self, max_attempts: int = 5, backoff_base: float = 0.5
    ) -> int:
        # Attempt to reconcile queued dual-write failures. Returns number of processed entries.
        if not self.redis:
            raise RuntimeError("redis required for reconciliation")
        key = "reconcile_queue"
        processed = 0
        # naive loop limited by max_attempts to avoid long-running jobs
        while self.redis.llen(key) > 0 and processed < max_attempts:
            item = self.redis.rpop(key)
            if not item:
                break
            try:
                payload = json.loads(item)
                rec = payload.get("record")
                # attempt dual write again
                if self.db_primary:
                    if self.db_secondary:
                        self.db_primary.dual_write(rec, self.db_secondary)
                    else:
                        self.db_primary.write(rec)
                processed += 1
            except Exception:
                # failed again: re-enqueue the original raw item (avoid undefined 'record')
                try:
                    # push back the raw item into the queue for later processing
                    self.redis.lpush(key, item)
                except Exception:
                    logger.exception("re-enqueue failed during reconciliation")
                # backoff a bit
                time.sleep(backoff_base * (processed + 1))
                break
        return processed

    # Legal Hold / eDiscovery APIs
    def set_legal_hold(self, case_id: str) -> None:
        if not self.redis:
            raise RuntimeError("redis required for legal hold")
        self.redis.set(self._legal_hold_prefix + case_id, True)

    def release_legal_hold(self, case_id: str) -> None:
        if not self.redis:
            raise RuntimeError("redis required for legal hold")
        self.redis.delete(self._legal_hold_prefix + case_id)

    def export_ediscovery(self, case_id: str) -> Dict[str, Any]:
        # Export historical records for a case_id with WORM-like signed bundle
        if not self.db_primary:
            raise RuntimeError("primary DB required for eDiscovery")
        records = self.db_primary.query_by_case(case_id)
        bundle = {
            "case_id": case_id,
            "records": records,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # ensure Decimals inside bundle are stringified for export
        payload = json.dumps(bundle, sort_keys=True, default=lambda o: str(o)).encode(
            "utf-8"
        )
        sig = ""
        key_version = ""
        algorithm = ""
        fingerprint = ""
        try:
            if self.kms and hasattr(self.kms, "sign"):
                sig_bytes = self.kms.sign(payload)
                sig = base64.b64encode(sig_bytes).decode("ascii")
                algorithm = getattr(self.kms, "algorithm", "RSA-4096")
                key_version = getattr(self.kms, "key_version", "unknown")
                fingerprint = hashlib.sha256(
                    getattr(self.kms, "public_key_bytes", b"")
                ).hexdigest()
        except Exception:
            logger.exception("failed to sign eDiscovery bundle")

        return {
            "bundle": bundle,
            "signature": {
                "algorithm": algorithm,
                "key_version": key_version,
                "signature": sig,
                "public_key_fingerprint": fingerprint,
            },
        }

    # Core execution (single)
    def _execute(self, payload: Dict[str, Any]) -> CalculationData:
        start = time.time()
        self._metric_calls.inc()

        # Rate limiting per-call
        if not self.rate_limiter.consume():
            raise RuntimeError("rate limit exceeded")

        # Circuit breaker guard
        if not self.circuit_breaker.call_allowed():
            raise RuntimeError("circuit open")

        # Enforce payload size
        raw = json.dumps(payload)
        if len(raw.encode("utf-8")) > self.payload_size_limit:
            raise MemoryError("payload too large")

        # Sanitization and schema validation
        payload = sanitize_input(payload)
        self._validate_schema(payload)

        # Functional, pure Decimal calculations
        items = payload.get("items", [])
        tenant = str(payload.get("tenant_id"))

        with localcontext() as ctx:
            ctx.prec = 28
            total = Decimal(0)
            taxes = Decimal(0)
            for it in items:
                # Expect item to have 'amount' and 'tax_pct'
                amt = Decimal(str(it.get("amount")))
                tax_pct = Decimal(str(it.get("tax_pct", "0")))
                total += amt
                taxes += (amt * tax_pct) / Decimal(100)

        data = CalculationData(
            tenant_id=tenant, total=total, taxes=taxes, items_count=len(items)
        )

        proc_ms = int((time.time() - start) * 1000)
        self._metric_processing_ms.set(proc_ms)
        self.circuit_breaker.record_success()

        return data

    # Bulk execution with isolation and retries
    def _execute_bulk(
        self, payloads: List[Dict[str, Any]], *, max_workers: int = 4, retry: int = 2
    ) -> List[CalculationData]:
        results: List[CalculationData] = []

        def worker(pl: Dict[str, Any]) -> CalculationData:
            # Bulkhead acquire
            if not self._bulkhead.acquire(timeout=10):
                raise RuntimeError("bulkhead busy")
            try:
                attempt = 0
                while True:
                    try:
                        return self._execute(pl)
                    except Exception:
                        attempt += 1
                        if attempt > retry:
                            self.circuit_breaker.record_failure()
                            raise
                        time.sleep(0.1 * attempt)
            finally:
                self._bulkhead.release()

        with ThreadPoolExecutor(max_workers=min(max_workers, len(payloads) or 1)) as ex:
            futures = {ex.submit(worker, p): p for p in payloads}
            for fut in as_completed(futures):
                results.append(fut.result())

        return results

    # Public functional wrapper
    def executar(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Enclose in telemetry span if available
        tracer = getattr(trace, "get_tracer", lambda name: trace)("sovereign")
        with tracer.start_as_current_span("sovereign.execute"):
            # RBAC/OIDC enforcement: if IDP configured, require valid token and role
            try:
                if self.idp:
                    auth = payload.get("auth") or {}
                    token = auth.get("token") or payload.get("auth_token")
                    required_role = (
                        auth.get("required_role")
                        or payload.get("required_role")
                        or "processor"
                    )
                    if not token or not self.idp.check_rbac(token, required_role):
                        logger.warning(
                            "RBAC check failed for token=%s role=%s",
                            mask_pii(token),
                            required_role,
                        )
                        return {
                            "status": "error",
                            "data": None,
                            "provenance": {"error": "rbac_denied"},
                        }
            except Exception:
                logger.exception("RBAC enforcement failed")
                return {
                    "status": "error",
                    "data": None,
                    "provenance": {"error": "rbac_enforcement_failure"},
                }
            # safety: reject deep recursion attempts in payload
            raw_json = json.dumps(payload)
            if raw_json.count("{") > self.recursion_depth_limit * 2:
                raise MemoryError("recursion_depth exceeded")

            # Run setup
            self._setup()

            # Execute
            try:
                data = self._execute(payload)
                status = "success"
            except Exception:
                logger.exception("execution failed")
                status = "error"
                data = None

            # Build provenance
            provenance = self._build_provenance(payload, data, status)

            result = {
                "status": status,
                "data": asdict(data) if data else None,
                "provenance": provenance,
            }

            # Teardown
            try:
                self._teardown()
            except Exception:
                logger.debug("teardown failed")

            return result

    def _build_provenance(
        self, payload: Dict[str, Any], data: Optional[CalculationData], status: str
    ) -> Dict[str, Any]:
        # Prepare signature over canonical payload+result
        # ensure Decimal and other non-JSON types are stringified for signing
        payload_bytes = json.dumps(
            {"payload": payload, "data": asdict(data) if data else None},
            sort_keys=True,
            default=lambda o: str(o),
        ).encode("utf-8")
        signature_b64 = ""
        key_fingerprint = ""
        algorithm = ""
        key_version = ""
        try:
            if self.kms and hasattr(self.kms, "sign"):
                sig = self.kms.sign(payload_bytes)
                signature_b64 = base64.b64encode(sig).decode("ascii")
                algorithm = getattr(self.kms, "algorithm", "RSA-4096")
                key_version = getattr(self.kms, "key_version", "unknown")
                pub = getattr(self.kms, "public_key_bytes", b"")
                if pub:
                    key_fingerprint = hashlib.sha256(pub).hexdigest()
            else:
                # best-effort local sign if KMS not present (not for production)
                m = hashlib.sha256()
                m.update(payload_bytes)
                signature_b64 = base64.b64encode(m.digest()).decode("ascii")
                algorithm = "SHA256"
                key_version = "local"
                key_fingerprint = hashlib.sha256(b"local_key").hexdigest()
        except Exception:
            logger.exception("signing failed for provenance")

        forensic_hash = hashlib.sha256(payload_bytes).hexdigest()

        telemetry = {"trace_id": None, "processing_ms": 0, "memory_usage_bytes": 0}

        try:
            # try to attach telemetry info
            telemetry["trace_id"] = None
            telemetry["processing_ms"] = int(0)
            import psutil

            telemetry["memory_usage_bytes"] = psutil.Process().memory_info().rss
        except Exception:
            telemetry["memory_usage_bytes"] = 0

        prov = {
            "tool_version": self.__version__,
            "signature": {
                "algorithm": algorithm,
                "key_version": key_version,
                "signature": signature_b64,
                "public_key_fingerprint": key_fingerprint,
            },
            "regulatory_compliance": {
                "framework": "LGPD|GDPR",
                "data_residency": payload.get("data_residency", "br-saopaulo"),
                "processing_basis": payload.get(
                    "processing_basis", "contractual_necessity"
                ),
            },
            "forensic_metadata": {
                "legal_hold_active": bool(payload.get("legal_hold_active", False)),
                "chain_of_custody_hash": forensic_hash,
            },
            "telemetry": telemetry,
        }

        return prov


__all__ = ["SovereignCalculationTool", "SovereignToolManifest", "CalculationData"]
