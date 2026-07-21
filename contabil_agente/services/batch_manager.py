import asyncio
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

logger = logging.getLogger(__name__)

try:
    from contabil_agente.services.audit_service import AuditService
except Exception:
    AuditService = None
try:
    from contabil_agente.services.delivery_service import DeliveryService
except Exception:
    DeliveryService = None
try:
    from contabil_agente.services.database_service import DatabaseService
except Exception:
    DatabaseService = None


class BatchManager:
    """Gerencia processamento em lote com checkpointing e rate-limiting.

    - checkpoint_file: salva progresso para retomada
    - concurrency: número de workers paralelos
    - rate_limit_per_min: limites de requisições iniciadas por minuto
    """

    def __init__(
        self,
        checkpoint_file: str = "checkpoint.json",
        concurrency: int = 3,
        rate_limit_per_min: int = 30,
    ):
        self.checkpoint_file = Path(checkpoint_file)
        self.concurrency = concurrency
        self.rate_limit_per_min = rate_limit_per_min
        self._last_start = 0.0
        self._db = DatabaseService() if DatabaseService else None

    def _audit(self, msg: str):
        try:
            if AuditService:
                a = AuditService.get_instance()
                a.log_operation(msg)
                return
        except Exception:
            pass
        logger.info("AUDIT: %s", msg)

    def load_checkpoint(self) -> Dict[str, Any]:
        if not self.checkpoint_file.exists():
            return {"completed": {}, "index": 0}
        try:
            return json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            return {"completed": {}, "index": 0}

    def save_checkpoint(self, checkpoint: Dict[str, Any]) -> None:
        try:
            self.checkpoint_file.write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to write checkpoint")

    async def _rate_limit_wait(self):
        if self.rate_limit_per_min <= 0:
            return
        interval = 60.0 / float(self.rate_limit_per_min)
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_start
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        self._last_start = asyncio.get_event_loop().time()

    async def process(
        self, cnpjs: Iterable[str], worker_coro: Callable[[str], Any]
    ) -> Dict[str, Any]:
        # worker_coro must be an async callable that accepts cnpj and returns a dict with status
        checkpoint = self.load_checkpoint()
        completed = checkpoint.get("completed", {})
        results: Dict[str, Any] = {}

        db = self._db

        # Enqueue tasks into persistent DB queue
        if db:
            for cnpj in cnpjs:
                try:
                    payload = {"cnpj": cnpj}
                    db.enqueue_task(cnpj, payload, priority="BATCH")
                except Exception:
                    logger.debug("failed to enqueue %s in DB queue", cnpj)
        else:
            # fallback: use in-memory list
            for cnpj in cnpjs:
                checkpoint.setdefault("pending", []).append(cnpj)

        # Pre-flight health checks: delivery & portal
        try:
            delivery = DeliveryService() if DeliveryService else None
            delivery_health = (
                delivery.health_check()
                if delivery
                else {"smtp": False, "whatsapp": False}
            )
            self._audit(f"PREFLIGHT delivery_health={json.dumps(delivery_health)}")
            # Basic portal reachability check using HEAD
            try:

                def _head(url: str):
                    req = urllib.request.Request(url, method="HEAD")
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return r.status

                # try a common gov URL as a light check
                portal_ok = await asyncio.to_thread(
                    _head, "https://www.receita.fazenda.gov.br"
                )
                self._audit(f"PREFLIGHT portal_status={portal_ok}")
            except Exception as e:
                self._audit(f"PREFLIGHT portal_unreachable: {e}")
        except Exception:
            pass

        sem = asyncio.Semaphore(self.concurrency)

        async def _worker_loop():
            while True:
                async with sem:
                    await self._rate_limit_wait()
                    # claim from DB
                    task = None
                    if db:
                        try:
                            t = db.claim_task("BATCH")
                            if t:
                                task = t
                                task_id = task.get("id")
                                payload = json.loads(task.get("payload") or "{}")
                                cnpj = payload.get("cnpj")
                            else:
                                await asyncio.sleep(0.5)
                                continue
                        except Exception:
                            await asyncio.sleep(1)
                            continue
                    else:
                        # fallback: pop from checkpoint pending
                        pend = checkpoint.get("pending", [])
                        if not pend:
                            await asyncio.sleep(0.5)
                            continue
                        cnpj = pend.pop(0)

                    start = asyncio.get_event_loop().time()
                    try:
                        res = await worker_coro(cnpj)
                        res["started_at"] = start
                        results[cnpj] = res
                        completed[cnpj] = res.get("status", "unknown")
                        checkpoint["completed"] = completed
                        self.save_checkpoint(checkpoint)
                        self._audit(f"BATCH_PROCESSED {cnpj} -> {res.get('status')}")
                        # mark DB
                        if db and task:
                            db.complete_task(task_id)
                    except Exception as e:
                        logger.exception("Error processing %s: %s", cnpj, e)
                        results[cnpj] = {"status": "failed", "reason": str(e)}
                        completed[cnpj] = "failed"
                        checkpoint["completed"] = completed
                        self.save_checkpoint(checkpoint)
                        self._audit(f"BATCH_ERROR {cnpj}: {e}")
                        if db and task:
                            db.fail_task(task_id, str(e))

        # spawn worker loops
        workers = [asyncio.create_task(_worker_loop()) for _ in range(self.concurrency)]
        # wait for queues to drain (DB-backed) or initial tasks to complete
        try:
            # simple wait: monitor until no pending tasks in DB
            while True:
                if db:
                    with db._lock:
                        cur = db._conn.cursor()
                        cur.execute(
                            "SELECT COUNT(1) as c FROM tasks WHERE state IN ('PENDENTE','PROCESSANDO')"
                        )
                        row = cur.fetchone()
                        cur.close()
                    pending = int(row[0]) if row else 0
                    if pending == 0:
                        break
                else:
                    pend = checkpoint.get("pending", [])
                    if not pend:
                        break
                await asyncio.sleep(1)
        finally:
            for w in workers:
                w.cancel()

        # produce summary
        summary = {"total": len(results), "by_status": {}}
        for c, r in results.items():
            summary["by_status"].setdefault(r.get("status", "unknown"), 0)
            summary["by_status"][r.get("status", "unknown")] += 1
        self._audit(f"BATCH_COMPLETE summary={json.dumps(summary)}")
        return {"results": results, "summary": summary}

    def maintenance_cleanup(self) -> Dict[str, int]:
        """Archive completed tasks >90 days and delete evidence >180 days."""
        db = self._db
        out = {"archived_tasks": 0, "deleted_evidence_files": 0}
        try:
            if db:
                out["archived_tasks"] = db.archive_old_completed(days=90)
                out["deleted_evidence_files"] = db.delete_old_evidence(days=180)
        except Exception:
            logger.exception("maintenance cleanup failed")
        return out

    def get_health(self) -> Dict[str, any]:
        """Aggregate health from DB, delivery and disk."""
        out: Dict[str, any] = {"ok": False}
        try:
            db = self._db
            if db:
                dout = db.health_check()
                out.update({"db": dout})
            delivery = DeliveryService() if DeliveryService else None
            out["delivery"] = (
                delivery.health_check()
                if delivery
                else {"smtp": False, "whatsapp": False}
            )
            out["ok"] = True
        except Exception as e:
            out["error"] = str(e)
        return out

    def prometheus_metrics(self) -> str:
        """Return simple Prometheus exposition text for metrics collected."""
        lines = []
        with self._metrics_lock:
            for name, m in self._metrics.items():
                times = m.get("times", [])
                avg = sum(times) / len(times) if times else 0.0
                lines.append(f'agent_worker_avg_seconds{{worker="{name}"}} {avg}')
                lines.append(
                    f'agent_worker_success_total{{worker="{name}"}} {m.get("success", 0)}'
                )
                lines.append(
                    f'agent_worker_failure_total{{worker="{name}"}} {m.get("failure", 0)}'
                )
        return "\n".join(lines)

    def generate_dashboard(
        self, results: Dict[str, Any], out_path: str = "dashboard.html"
    ) -> None:
        # Minimal HTML dashboard generation
        rows = []
        for cnpj, info in results.items():
            status = info.get("status")
            path = info.get("path", "")
            metrics = info.get("metrics", {})
            evidence_link = ""
            rows.append((cnpj, status, path, metrics, evidence_link))

        html = [
            "<html><head><meta charset='utf-8'><title>Batch Dashboard</title></head><body>"
        ]
        html.append("<h1>Batch Dashboard</h1>")
        html.append("<table border='1' style='width:100%'>")
        html.append("<tr><th>CNPJ</th><th>Status</th><th>PDF</th><th>Metrics</th></tr>")
        for r in rows:
            metrics_json = json.dumps(r[3])
            pdf_link = f"<a href='{r[2]}'>PDF</a>" if r[2] else ""
            html.append(
                f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{pdf_link}</td><td>{metrics_json}</td></tr>"
            )
        html.append("</table></body></html>")

        try:
            Path(out_path).write_text("\n".join(html), encoding="utf-8")
        except Exception:
            logger.exception("Failed to write dashboard")


__all__ = ["BatchManager"]
