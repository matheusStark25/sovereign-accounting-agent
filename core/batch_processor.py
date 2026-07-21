from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List
import threading
import traceback
import signal
import json
import time
from decimal import Decimal
from pathlib import Path

from models.rescisao import RescisaoInput
from core.interfaces import CalculoToolProtocol, PDFToolProtocol, AuditServiceProtocol
from core.monitor import MetricsCollector, Timer
from core.cache import CalculationCache
from utils.csv_handler import CSVHandler
from utils.retry import retry
from core.config import load_settings
from core.checkpoint import Checkpoint
from core.atomic_writer import compute_hash, atomic_write_bytes
from utils.pdf_generator import generate_trct_pdf


class BatchProcessor:
    """Batch processing orchestrator with DI, threading, circuit breaker and retries.

    - Inject `calculo_tool`, `pdf_tool`, `audit_service`
    - Uses ThreadPoolExecutor(max_workers=4)
    - Circuit breaker for PDF tool: opens after 3 consecutive PDF failures
    - PDF generation wrapped with retry decorator (3 attempts, exponential backoff)
    """

    def __init__(
        self,
        calculo_tool: CalculoToolProtocol,
        pdf_tool: PDFToolProtocol,
        audit_service: AuditServiceProtocol,
        metrics: MetricsCollector | None = None,
        cache: CalculationCache | None = None,
    ) -> None:
        self.calculo_tool = calculo_tool
        self.pdf_tool = pdf_tool
        self.audit = audit_service
        self.metrics = metrics or MetricsCollector()
        self.cache = cache or CalculationCache()

        self._executor = ThreadPoolExecutor(max_workers=4)
        self._pdf_failure_count = 0
        self._pdf_circuit_open = False
        self._lock = threading.Lock()
        self._shutdown_requested = False

        # load settings and checkpoint
        self.settings = load_settings()
        self._checkpoint = Checkpoint(self.settings.CHECKPOINT_FILE)
        (Path(self.settings.OUTPUT_PATH) / "pdfs").mkdir(parents=True, exist_ok=True)

        # register signals for graceful shutdown
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except Exception:
            # not all platforms support signal setting (e.g., Windows in some contexts)
            pass

        # wrap pdf call with retry
        self._pdf_with_retry = retry(max_attempts=3)(self._call_generate_pdf)

    def _call_generate_pdf(self, payload: Dict[str, Any]) -> bytes:
        # prefer the pdf generator util for consistent template
        return generate_trct_pdf(payload)

    def _handle_signal(self, signum, frame) -> None:
        self.audit.info(f"Shutdown signal received: {signum}")
        self._shutdown_requested = True

    def _should_generate_pdf(self) -> bool:
        with self._lock:
            return not self._pdf_circuit_open

    def _record_pdf_success(self) -> None:
        with self._lock:
            self._pdf_failure_count = 0
            if self._pdf_circuit_open:
                # closing circuit
                self._pdf_circuit_open = False
                self.audit.info("PDF circuit closed; resuming PDF generations")

    def _record_pdf_failure(self) -> None:
        with self._lock:
            self._pdf_failure_count += 1
            if self._pdf_failure_count >= 3 and not self._pdf_circuit_open:
                self._pdf_circuit_open = True
                self.audit.critical(
                    "PDFTool failed 3 times consecutively: opening circuit and skipping future PDFs"
                )

    def process_batch(
        self, csv_handler: CSVHandler, output_filename: str = "results.csv"
    ) -> None:
        """Process all rows from CSVHandler, perform calculations and optionally generate PDFs.

        The method ensures individual errors do not stop the batch.
        """

        rows = list(csv_handler.read_rows())
        results: List[Dict[str, Any]] = []
        futures = []

        # resume from checkpoint if present
        last_checkpoint = self._checkpoint.read()
        if last_checkpoint:
            self.audit.info(f"Found checkpoint, will resume after id {last_checkpoint}")

        def worker(row: Dict[str, str]) -> Dict[str, Any]:
            out: Dict[str, Any] = {"error": "", "pdf_generated": False}
            try:
                # Validate input via Pydantic
                resc = RescisaoInput(**row)
            except Exception as e:
                out.update(
                    {
                        "id": row.get("id", ""),
                        "nome": row.get("nome", ""),
                        "error": f"validation:{e}",
                    }
                )
                self.metrics.inc_failure()
                self.audit.error(
                    json.dumps(
                        {
                            "event": "validation_failed",
                            "id": row.get("id"),
                            "error": str(e),
                        }
                    )
                )
                return out

            # Calculation with cache: create cached wrapper for the calculo_tool
            @self.cache.cached
            def _calc_cached(salario_base: float, data_admissao: Any):
                # rebuild a minimal RescisaoInput for call
                fake = RescisaoInput(
                    id=resc.id,
                    nome=resc.nome,
                    salario_base=salario_base,
                    data_admissao=data_admissao,
                    data_demissao=resc.data_demissao,
                    motivo=resc.motivo,
                )
                return self.calculo_tool.calculate(fake)

            try:
                with Timer(self.metrics):
                    # Use Decimal for monetary precision (safe conversion)
                    try:
                        resc.salario_base = Decimal(str(resc.salario_base))
                    except Exception:
                        resc.salario_base = Decimal("0")
                    calc_result = _calc_cached(resc.salario_base, resc.data_admissao)
                out.update(calc_result)
                self.metrics.inc_success()
            except Exception as e:
                out.update({"id": resc.id, "nome": resc.nome, "error": f"calc:{e}"})
                self.metrics.inc_failure()
                self.audit.error(
                    json.dumps(
                        {
                            "event": "calculation_failed",
                            "id": resc.id,
                            "error": str(e),
                            "trace": traceback.format_exc(),
                        }
                    )
                )
                return out

            # PDF generation (if circuit permits)
            if self._should_generate_pdf():
                try:
                    # generate initial pdf bytes without embedded hash
                    pdf_bytes_initial = self._pdf_with_retry(out)

                    # compute integrity hash of initial bytes
                    initial_hash = compute_hash(
                        pdf_bytes_initial, self.settings.SIGNATURE_KEY
                    )

                    # now regenerate PDF embedding metadata (company and integrity)
                    metadata = {
                        "author": self.settings.COMPANY_NAME,
                        "title": f"TRCT - {resc.id}",
                        "subject": f"integrity:{initial_hash}",
                    }
                    pdf_bytes_final = generate_trct_pdf(out, metadata=metadata)

                    # final integrity over final bytes
                    final_hash = compute_hash(
                        pdf_bytes_final, self.settings.SIGNATURE_KEY
                    )

                    # atomic write final bytes
                    out_pdf = (
                        Path(self.settings.OUTPUT_PATH) / "pdfs" / f"{resc.id}.pdf"
                    )
                    atomic_write_bytes(out_pdf, pdf_bytes_final)

                    # write metadata sidecar with both hashes
                    meta = {
                        "id": resc.id,
                        "initial_hash": initial_hash,
                        "final_hash": final_hash,
                        "generated_at": time.time(),
                    }
                    meta_path = out_pdf.with_suffix(out_pdf.suffix + ".meta.json")
                    tmp_meta = meta_path.with_suffix(meta_path.suffix + ".tmp")
                    tmp_meta.write_text(json.dumps(meta), encoding="utf-8")
                    tmp_meta.replace(meta_path)

                    out["pdf_generated"] = True
                    out["pdf_hash"] = final_hash
                    self._record_pdf_success()
                except Exception as e:
                    out["pdf_generated"] = False
                    self._record_pdf_failure()
                    self.metrics.inc_failure()
                    # log structured error with stack
                    self.audit.error(
                        json.dumps(
                            {
                                "event": "pdf_failed",
                                "id": resc.id,
                                "error": str(e),
                                "trace": traceback.format_exc(),
                            }
                        )
                    )
            else:
                # Circuit open: skip PDF generation but continue
                self.audit.info(json.dumps({"event": "pdf_skipped", "id": resc.id}))

            return out

        # submit tasks, respect checkpoint and shutdown
        resume_after = last_checkpoint
        skipping = bool(resume_after)
        for row in rows:
            if self._shutdown_requested:
                break
            if skipping:
                if str(row.get("id")) == str(resume_after):
                    skipping = False
                continue
            futures.append(self._executor.submit(worker, row))

        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                # Shouldn't happen because worker catches errors, but guard anyway
                self.audit.error(f"Unexpected worker exception: {e}")

        # Ensure executor is cleanly shutdown so process can exit
        try:
            self._executor.shutdown(wait=True)
        except Exception:
            pass

        # Determine fieldnames and write results
        if results:
            fieldnames = list({k for r in results for k in r.keys()})
            csv_handler.write_results(output_filename, fieldnames, iter(results))

            # final report with batch integrity hash
            out_csv_path = Path(self.settings.OUTPUT_PATH) / output_filename
            try:
                batch_bytes = out_csv_path.read_bytes()
                batch_hash = compute_hash(batch_bytes, self.settings.SIGNATURE_KEY)
                final = {
                    "total": len(results),
                    "success": sum(1 for r in results if not r.get("error")),
                    "failure": sum(1 for r in results if r.get("error")),
                    "latencia_media": self.metrics.latency_media(),
                    "batch_hash": batch_hash,
                }
                final_path = Path(self.settings.OUTPUT_PATH) / "final_report.json"
                final_path.write_text(json.dumps(final, indent=2), encoding="utf-8")
            except Exception:
                self.audit.error(
                    json.dumps(
                        {
                            "event": "final_report_failed",
                            "error": "could not write final report",
                        }
                    )
                )
