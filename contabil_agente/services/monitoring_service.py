"""Monitoring service: supervises heartbeats, circuit breaker and exposes simple Prometheus metrics text.

Runs a supervisor loop that uses DatabaseService.check_workers() and sends webhooks when quarantines happen.
Also exposes `metrics_text()` which returns Prometheus-style metrics for scraping.
"""

from __future__ import annotations

import os
import threading
import time
import logging
import requests
import shutil
from pathlib import Path
from typing import Optional
import sys
import traceback

from contabil_agente.services.database_service import DatabaseService
from contabil_agente.services.telemetry_sanitizer import sanitize_event

logger = logging.getLogger("monitoring_service")


class MonitoringService:
    def __init__(self, interval: int = 60):
        try:
            self.db = DatabaseService()
        except Exception:
            self.db = None
        self.interval = interval
        # in-memory store for recent recovery events (sanitized at origin)
        self.recovery_events = []
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="MonitoringSrv"
        )

    def start(self):
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _notify(self, message: str):
        try:
            url = os.getenv("SLACK_WEBHOOK_URL") or os.getenv("TELEGRAM_WEBHOOK_URL")
            if url:
                requests.post(url, json={"text": message}, timeout=5)
        except Exception:
            logger.exception("notify webhook failed")

    def emergency_repair(self, step: str, error: Exception) -> dict:
        """Attempt a lightweight emergency repair and return an event dict.

        This is intentionally non-invasive: it performs simple cleanup like
        removing stale lock directories in the current working directory
        and returns a structured trace useful for post-mortem analysis.
        """
        start = time.perf_counter()
        ev = {
            "step": step,
            "error_type": error.__class__.__name__ if error is not None else "None",
            "error_file": None,
            "error_line": None,
            "error_message": str(error) if error is not None else None,
            "stack_trace": None,
            "repair_action": None,
            "duration_ms": None,
        }
        try:
            # simple repair: remove stale lock dirs in cwd matching pattern
            removed = []
            try:
                cwd = Path.cwd()
                for p in cwd.iterdir():
                    try:
                        if p.is_dir() and p.name.startswith(".lock_"):
                            try:
                                shutil.rmtree(p)
                                removed.append(str(p))
                            except Exception:
                                try:
                                    p.rmdir()
                                    removed.append(str(p))
                                except Exception:
                                    pass
                    except Exception:
                        continue
            except Exception:
                removed = []

            ev["repair_action"] = f"removed_locks:{removed}"
        except Exception:
            ev["repair_action"] = "failed_repair_attempt"
        finally:
            ev["duration_ms"] = int((time.perf_counter() - start) * 1000.0)
        try:
            # Robust capture: prefer sys.exc_info() for the current exception context
            try:
                exc_type, exc_value, exc_tb = sys.exc_info()
                # If sys.exc_info() did not return a traceback, fall back to the exception's __traceback__
                if (
                    exc_tb is None
                    and error is not None
                    and hasattr(error, "__traceback__")
                ):
                    exc_tb = error.__traceback__

                if exc_tb is not None:
                    tb_list = traceback.extract_tb(exc_tb)
                    if tb_list:
                        last = tb_list[-1]
                        fname = getattr(last, "filename", None)
                        # normalize to absolute path so sanitizer can match project root
                        try:
                            ev_file = os.path.abspath(fname) if fname else None
                        except Exception:
                            ev_file = fname
                        ev["error_file"] = ev_file if ev_file else "UNKNOWN_LOCATION"
                        ev["error_line"] = (
                            getattr(last, "lineno", None) or "UNKNOWN_LOCATION"
                        )
                    # full stack trace string — keep full paths for sanitizer to redact
                    ev["stack_trace"] = "".join(
                        traceback.format_exception(
                            exc_type or type(error), exc_value or error, exc_tb
                        )
                    )
                else:
                    # If no traceback available from sys.exc_info or the exception object,
                    # attempt to capture the current call stack to infer caller location.
                    try:
                        stack = traceback.extract_stack()
                        # pick the most-recent frame outside this monitoring module
                        picked = None
                        for fr in reversed(stack):
                            if (
                                fr.filename
                                and "monitoring_service.py" not in fr.filename
                            ):
                                picked = fr
                                break
                        if picked:
                            pf = getattr(picked, "filename", None)
                            # normalize to absolute path so sanitizer can match project root
                            try:
                                ev_pf = os.path.abspath(pf) if pf else None
                            except Exception:
                                ev_pf = pf
                            ev["error_file"] = ev_pf if ev_pf else "UNKNOWN_LOCATION"
                            ev["error_line"] = (
                                getattr(picked, "lineno", None) or "UNKNOWN_LOCATION"
                            )
                        # format the captured stack and preserve full paths for sanitizer
                        try:
                            st = "".join(traceback.format_list(stack)) or ""
                            ev["stack_trace"] = st or "UNKNOWN_LOCATION"
                        except Exception:
                            ev["stack_trace"] = "UNKNOWN_LOCATION"
                    except Exception:
                        # fallback: capture whatever format_exc() returns for the last exception context
                        try:
                            formatted = traceback.format_exc()
                            ev["stack_trace"] = (
                                formatted
                                if formatted and formatted.strip()
                                else "UNKNOWN_LOCATION"
                            )
                        except Exception:
                            ev["stack_trace"] = "UNKNOWN_LOCATION"

                # Ensure file/line are non-null strings
                if not ev.get("error_file"):
                    ev["error_file"] = "UNKNOWN_LOCATION"
                if not ev.get("error_line"):
                    ev["error_line"] = "UNKNOWN_LOCATION"
                # Sanitize event at origin so telemetry is born clean and store it
                try:
                    ev_sanitized = sanitize_event(ev)
                    # append sanitized event to in-memory list for inspection
                    try:
                        self.recovery_events.append(ev_sanitized)
                    except Exception:
                        # best-effort append; ignore failures to avoid raising in monitoring
                        pass
                    ev = ev_sanitized
                except Exception:
                    # if sanitizer fails, keep original ev
                    pass
            except Exception:
                # absolute last-resort: mark unknowns
                ev["stack_trace"] = ev.get("stack_trace") or "UNKNOWN_LOCATION"
                ev["error_file"] = ev.get("error_file") or "UNKNOWN_LOCATION"
                ev["error_line"] = ev.get("error_line") or "UNKNOWN_LOCATION"

            logger.info("emergency_repair executed", extra={"event": ev})
        except Exception:
            # swallow logging errors - we don't want monitoring to raise
            pass
        return ev

    def _loop(self):
        while not self._stop.is_set():
            try:
                if not self.db:
                    time.sleep(self.interval)
                    continue
                res = self.db.check_workers()
                quarantined = res.get("quarantined", [])
                if quarantined:
                    for w in quarantined:
                        self._notify(f"Worker {w} quarantined - monitoring_service")
            except Exception:
                logger.exception("monitor loop error")
            self._stop.wait(self.interval)

    def metrics_text(self) -> str:
        """Return a small set of Prometheus metrics as text/plain."""
        lines = []
        try:
            if not self.db:
                return "# monitoring_service: no db\n"
            total = self.db.get_tasks_total()
            dlq = self.db.get_dlq_size()
            cls = self.db.get_classification_count()
            xmls = 0
            try:
                with self.db._lock:
                    cur = self.db._conn.cursor()
                    cur.execute("SELECT COUNT(1) FROM xml_documents")
                    row = cur.fetchone()
                    xmls = int(row[0]) if row else 0
                    cur.close()
            except Exception:
                xmls = 0

            lines.append(f"contabil_tasks_total {total}")
            lines.append(f"contabil_tasks_dead_letter {dlq}")
            lines.append(f"contabil_classifications_total {cls}")
            lines.append(f"contabil_xml_documents_total {xmls}")
        except Exception:
            lines.append("# metrics error")
        return "\n".join(lines) + "\n"


_MON: Optional[MonitoringService] = None


def get_monitoring_service() -> MonitoringService:
    global _MON
    if _MON is None:
        _MON = MonitoringService()
        _MON.start()
    return _MON
