from __future__ import annotations
import asyncio
import json
from typing import Any
import os

try:
    from arq import create_pool
    from arq.connections import RedisSettings

    ARQ_AVAILABLE = True
except Exception:
    create_pool = None
    RedisSettings = None
    ARQ_AVAILABLE = False

from .storage import LocalStorage
from .storage import S3Storage
from .utils.resilience import retry_backoff
from .utils.resilience import CircuitBreaker
from .document_processor import DocumentProcessor
from .audit import AuditLogger
from .config import settings

try:
    import httpx
except Exception:
    httpx = None


REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")

# Circuit breakers for infra
REDIS_BREAKER = CircuitBreaker(name="redis")

# Simple semaphores to isolate resource usage per worker type
_SEM_PDF = asyncio.Semaphore(2)
_SEM_IMAGE = asyncio.Semaphore(4)
_SEM_XML = asyncio.Semaphore(2)
_SEM_CSV = asyncio.Semaphore(4)


async def enqueue_document_job(
    file_bytes: bytes,
    filename: str,
    webhook: str | None = None,
    user_id: str | None = None,
    audit_id: str | None = None,
) -> str:
    # determine job name by file type so specialized workers can be scheduled
    lower = filename.lower()
    if lower.endswith(".pdf"):
        job_name = "process_pdf"
    elif lower.endswith((".png", ".jpg", ".jpeg", ".tiff")):
        job_name = "process_image"
    elif lower.endswith((".xml",)):
        job_name = "process_xml"
    elif lower.endswith((".csv", ".txt")):
        job_name = "process_tabular"
    else:
        job_name = "process_document"

    if not ARQ_AVAILABLE or create_pool is None:
        # ARQ not installed in this environment: run inline for development/test
        # Return a synthetic job id and run the processor synchronously.
        await process_document(None, file_bytes, filename, webhook, user_id, audit_id)
        return f"local::{filename}"

    pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    async with pool:
        # pass user context to worker as args so worker can audit
        job = await pool.enqueue_job(
            job_name, file_bytes, filename, webhook, user_id, audit_id
        )
        return job.job_id


async def _run_with_semaphore(sem: asyncio.Semaphore, coro):
    async with sem:
        return await coro


async def process_document(
    ctx,
    file_bytes: bytes,
    filename: str,
    webhook: str | None = None,
    user_id: str | None = None,
    audit_id: str | None = None,
) -> dict[str, Any]:
    """ARQ worker function to process a document.

    - Stores original in configured storage (MinIO/S3) or local disk.
    - Runs DocumentProcessor (OCR/NER) with fallback.
    - Emits audit records for start/finish/fallbacks.
    """
    # select storage
    storage = None
    if settings.MINIO_ENDPOINT and settings.S3_BUCKET:
        storage = S3Storage(
            bucket=settings.S3_BUCKET,
            endpoint_url=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
        )
    else:
        storage = LocalStorage(".data/storage")

    audit = AuditLogger()
    cb = CircuitBreaker()
    processor = DocumentProcessor()

    async def _do_process():
        await audit.record(
            "ingest:start", user_id, audit_id or "", {"filename": filename}
        )

        # store original
        in_key = f"originals/{filename}"
        in_path = await storage.upload(in_key, file_bytes)

        # run extraction
        result = await processor.process(file_bytes, filename)

        # if fallback used register it
        if result.get("fallback_used"):
            await audit.record(
                "ingest:fallback_ner",
                user_id,
                audit_id or "",
                {"filename": filename, "reason": "ner_confidence_low"},
            )

        # produce artifact (for now: text summary)
        out_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")
        out_key = f"processed/{filename}.json"
        out_path = await storage.upload(out_key, out_bytes)

        await audit.record(
            "ingest:complete",
            user_id,
            audit_id or "",
            {
                "input": in_path,
                "output": out_path,
                "entities_count": len(result.get("entities", [])),
            },
        )
        return {"input": in_path, "output": out_path, "result": result}

    try:
        # default generic processing
        res = await retry_backoff(_do_process, attempts=3, base_delay=1.0)
        cb.record_success()
    except Exception as exc:
        cb.record_failure()
        await audit.record("ingest:error", user_id, audit_id or "", {"error": str(exc)})
        raise

    # send webhook if provided (best-effort, idempotency left to caller)
    if webhook and httpx is not None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                await client.post(webhook, json={"status": "done", "result": res})
            except Exception:
                pass

    return res


async def process_pdf(
    ctx,
    file_bytes: bytes,
    filename: str,
    webhook: str | None = None,
    user_id: str | None = None,
    audit_id: str | None = None,
):
    # specialized PDF worker with limited concurrency
    return await _run_with_semaphore(
        _SEM_PDF,
        process_document(ctx, file_bytes, filename, webhook, user_id, audit_id),
    )


async def process_image(
    ctx,
    file_bytes: bytes,
    filename: str,
    webhook: str | None = None,
    user_id: str | None = None,
    audit_id: str | None = None,
):
    return await _run_with_semaphore(
        _SEM_IMAGE,
        process_document(ctx, file_bytes, filename, webhook, user_id, audit_id),
    )


async def process_xml(
    ctx,
    file_bytes: bytes,
    filename: str,
    webhook: str | None = None,
    user_id: str | None = None,
    audit_id: str | None = None,
):
    return await _run_with_semaphore(
        _SEM_XML,
        process_document(ctx, file_bytes, filename, webhook, user_id, audit_id),
    )


async def process_tabular(
    ctx,
    file_bytes: bytes,
    filename: str,
    webhook: str | None = None,
    user_id: str | None = None,
    audit_id: str | None = None,
):
    return await _run_with_semaphore(
        _SEM_CSV,
        process_document(ctx, file_bytes, filename, webhook, user_id, audit_id),
    )
