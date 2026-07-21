from __future__ import annotations
import heapq
import json
import logging
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("operational_legacy_worker")

# Guarded imports — optional heavy deps

try:
    import pyautogui  # type: ignore
except Exception:
    pyautogui = None

try:
    import psutil
except Exception:
    psutil = None

try:
    from PIL import Image
except Exception:
    Image = None

try:
    import yaml
except Exception:
    yaml = None

try:
    from contabil_agente.services.database_service import DatabaseService
except Exception:
    DatabaseService = None


class JsonLoggerAdapter:
    """Log lines as JSON, never including secrets. Attach `correlation_id`."""

    def __init__(self, base_logger: logging.Logger):
        self.logger = base_logger

    def _safe_msg(self, msg: str, **meta) -> str:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "msg": msg}
        payload.update(
            {
                k: v
                for k, v in meta.items()
                if not k.lower().startswith("pass") and "secret" not in k.lower()
            }
        )
        return json.dumps(payload, ensure_ascii=False)

    def info(self, msg: str, **meta):
        self.logger.info(self._safe_msg(msg, **meta))

    def warning(self, msg: str, **meta):
        self.logger.warning(self._safe_msg(msg, **meta))

    def error(self, msg: str, **meta):
        self.logger.error(self._safe_msg(msg, **meta))

    def exception(self, msg: str, **meta):
        self.logger.exception(self._safe_msg(msg, **meta))


log = JsonLoggerAdapter(logger)


class FileLock:
    """Simple file lock per CNPJ using atomic create.

    Creates a lock file under `locks_dir/<cnpj>.lock`. Uses O_EXCL semantics.
    """

    def __init__(self, locks_dir: str):
        self.locks_dir = locks_dir
        os.makedirs(self.locks_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z_-]", "_", str(key))
        return os.path.join(self.locks_dir, f"{safe}.lock")

    def acquire(self, key: str, timeout: int = 30) -> bool:
        path = self._path(key)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                # atomic create
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)
                return True
            except FileExistsError:
                time.sleep(0.2)
            except Exception:
                time.sleep(0.5)
        return False

    def release(self, key: str) -> None:
        path = self._path(key)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


class PriorityQueue:
    """Priority queue favoring HIGH list items first, then NORMAL.

    Items are (priority_value, seq, (cnpj, payload)).
    """

    def __init__(self, high_list: Optional[List[str]] = None):
        self._heap: List[Tuple[int, int, Tuple[str, Dict[str, Any]]]] = []
        self._seq = 0
        self.high_set = set(high_list or [])
        self._lock = threading.Lock()

    def put(self, cnpj: str, payload: Dict[str, Any]):
        with self._lock:
            pr = 0 if cnpj in self.high_set else 1
            heapq.heappush(self._heap, (pr, self._seq, (cnpj, payload)))
            self._seq += 1

    def get(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        with self._lock:
            if not self._heap:
                return None
            _, _, item = heapq.heappop(self._heap)
            return item


class MetricBuffer:
    """Local buffer of metrics to batch-send when online.

    Persists to `buffer_file` to survive restarts.
    """

    def __init__(
        self, buffer_file: str, flush_interval: int = 60, batch_size: int = 50
    ):
        self.buffer_file = buffer_file
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.buffer_file), exist_ok=True)
        self._load()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _load(self):
        try:
            if os.path.exists(self.buffer_file):
                with open(self.buffer_file, "r", encoding="utf-8") as fh:
                    self._buf = json.load(fh)
            else:
                self._buf = []
        except Exception:
            self._buf = []

    def add(self, metric: Dict[str, Any]):
        with self._lock:
            self._buf.append(metric)
            self._persist()

    def _persist(self):
        try:
            with open(self.buffer_file, "w", encoding="utf-8") as fh:
                json.dump(self._buf, fh, ensure_ascii=False)
        except Exception:
            pass

    def _flush(self):
        # Attempt to send in batches (best-effort). Here we only drop on success.
        try:
            if not self._buf:
                return
            # simplistic check for network connectivity
            try:
                socket.create_connection(("8.8.8.8", 53), timeout=2).close()
            except Exception:
                return
            # pretend to POST to telemetry endpoint (project may replace with real)
            batches = []
            with self._lock:
                while self._buf:
                    batches.append(self._buf[: self.batch_size])
                    self._buf = self._buf[self.batch_size :]
                self._persist()
            for batch in batches:
                # best-effort: attempt to send via requests if available
                try:
                    import requests

                    # endpoint is pluggable via env
                    url = os.getenv("STARK_TELEMETRY_URL")
                    if not url:
                        continue
                    r = requests.post(url, json={"metrics": batch}, timeout=5)
                    if r.status_code not in (200, 201):
                        # requeue
                        with self._lock:
                            self._buf = batch + self._buf
                            self._persist()
                except Exception:
                    with self._lock:
                        self._buf = batch + self._buf
                        self._persist()
        except Exception:
            pass

    def _loop(self):
        while not self._stop.wait(self.flush_interval):
            try:
                self._flush()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        try:
            self._thread.join(timeout=2)
        except Exception:
            pass


class HealthHandler(threading.Thread):
    """Simple HTTP health endpoint exposing worker status."""

    def __init__(self, get_status_callable, host: str = "0.0.0.0", port: int = 9191):
        super().__init__(daemon=True)
        self.get_status = get_status_callable
        self.host = host
        self.port = port
        self._stop = threading.Event()

    def run(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        parent = self

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/health":
                    self.send_response(404)
                    self.end_headers()
                    return
                status = parent.get_status()
                s = json.dumps(status, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(s)))
                self.end_headers()
                self.wfile.write(s)

            def log_message(self, format, *args):
                return

        server = HTTPServer((self.host, self.port), _H)
        while not self._stop.is_set():
            server.handle_request()

    def stop(self):
        self._stop.set()


class OperationalLegacyWorker:
    """Worker implementing the 52-step operational flow with resilience.

    - Loads steps from YAML/JSON
    - Uses file locks per CNPJ
    - Persists checkpoints via DatabaseService
    - Watches system resources and adapts speed
    - Emits metrics to MetricBuffer
    - Supports plugin hooks
    """

    def __init__(
        self,
        base_path: Optional[str] = None,
        steps_config: Optional[str] = None,
        db: Optional[Any] = None,
        high_list: Optional[List[str]] = None,
        locks_dir: Optional[str] = None,
    ):
        self.base_path = base_path or os.getenv("STARK_BASE_PATH", "./stark_data")
        os.makedirs(self.base_path, exist_ok=True)
        self.locks_dir = locks_dir or os.path.join(self.base_path, "locks")
        os.makedirs(self.locks_dir, exist_ok=True)
        self.locker = FileLock(self.locks_dir)
        self.db = db or (DatabaseService() if DatabaseService else None)
        self.high_list = high_list or []
        self.pq = PriorityQueue(self.high_list)
        self.metric_buffer = MetricBuffer(
            os.path.join(self.base_path, "metrics_buffer.json")
        )
        self._stop = threading.Event()
        self._workers: List[threading.Thread] = []
        self._delay_multiplier = 1.0
        self._steps_cfg_path = steps_config or os.path.join(
            self.base_path, "operational_steps.yaml"
        )
        self.steps = self._load_steps(self._steps_cfg_path)
        self._seq = 0
        self.plugins = []
        self.health = {
            "running": True,
            "queue_size": 0,
            "cb_open": False,
            "delay_multiplier": self._delay_multiplier,
        }
        self.health_server = HealthHandler(self._get_health)
        # in-memory dedupe of enqueued tasks to avoid duplicates during resume
        self._enqueued_keys = set()

    def _get_health(self):
        self.health.update(
            {
                "queue_size": len(self.pq._heap),
                "delay_multiplier": self._delay_multiplier,
            }
        )
        return self.health

    def _load_steps(self, path: str) -> List[Dict[str, Any]]:
        if not os.path.exists(path):
            # create a default template with 52 step stubs
            template = [
                {"id": i + 1, "name": f"step_{i + 1}", "timeout": 30, "selector": None}
                for i in range(52)
            ]
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    if yaml:
                        yaml.safe_dump({"steps": template}, fh, allow_unicode=True)
                    else:
                        json.dump({"steps": template}, fh, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return template
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
                if yaml:
                    parsed = yaml.safe_load(raw)
                else:
                    parsed = json.loads(raw)
                steps = parsed.get("steps") if isinstance(parsed, dict) else parsed
                if not steps:
                    raise ValueError("no steps in config")
                return steps
        except Exception:
            log.exception("failed to load steps config, falling back to empty list")
            return []

    def register_plugin(self, plugin_mod):
        try:
            if hasattr(plugin_mod, "register"):
                plugin_mod.register(self)
            self.plugins.append(plugin_mod)
        except Exception:
            log.exception("plugin registration failed")

    def enqueue(self, cnpj: str, payload: Dict[str, Any]):
        # dedupe by (cnpj, correlation_id) to avoid in-memory duplicates
        correlation_id = None
        try:
            if isinstance(payload, dict):
                correlation_id = payload.get("correlation_id")
        except Exception:
            correlation_id = None
        key = (cnpj, correlation_id)
        if key in self._enqueued_keys:
            log.info(
                "enqueue_skipped_duplicate", cnpj=cnpj, correlation_id=correlation_id
            )
            return False
        self._enqueued_keys.add(key)
        self.pq.put(cnpj, payload)
        return True

    def start(self, worker_count: int = 2):
        # start health server
        self.health_server.start()
        # preflight checks
        ok, reason = self._preflight()
        if not ok:
            log.error("preflight_failed", reason=reason)
            return
        for _ in range(worker_count):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            self._workers.append(t)
            t.start()

    def stop(self):
        self._stop.set()
        self.metric_buffer.stop()
        try:
            self.health_server.stop()
        except Exception:
            pass

    def _preflight(self) -> Tuple[bool, Optional[str]]:
        # disk
        try:
            st = os.statvfs(self.base_path)
            free = (st.f_bavail * st.f_frsize) / (1024**3)
            if free < 10:
                return False, "low_disk"
        except Exception:
            log.warning("disk check skipped")
        # connectivity
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=2)
            sock.close()
        except Exception:
            return False, "network_unavailable"
        # permissions
        try:
            test = os.path.join(self.base_path, ".perm_test")
            with open(test, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(test)
        except Exception:
            return False, "permission_denied"
        return True, None

    def _worker_loop(self):
        while not self._stop.is_set():
            # adapt speed based on CPU/RAM
            self._observe_resources()
            item = self.pq.get()
            if not item:
                time.sleep(0.5 * self._delay_multiplier)
                continue
            cnpj, payload = item
            correlation_id = (
                payload.get("correlation_id") if isinstance(payload, dict) else None
            ) or f"op-{cnpj}-{int(time.time())}-{self._seq}"
            self._seq += 1
            key = (cnpj, correlation_id)
            try:
                started = time.time()
                ok = self._process_cnpj(cnpj, payload, correlation_id)
                elapsed = time.time() - started
                self.metric_buffer.add(
                    {
                        "cnpj": cnpj,
                        "duration": elapsed,
                        "ok": bool(ok),
                        "correlation_id": correlation_id,
                    }
                )
                log.info(
                    "processed",
                    cnpj=cnpj,
                    correlation_id=correlation_id,
                    ok=ok,
                    duration=elapsed,
                )
            except Exception:
                log.exception(
                    "processing failed", cnpj=cnpj, correlation_id=correlation_id
                )
            finally:
                try:
                    self._enqueued_keys.discard(key)
                except Exception:
                    pass

    def _observe_resources(self):
        try:
            if not psutil:
                return
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory().percent
            if cpu > 80 or mem > 80:
                self._delay_multiplier = min(10.0, self._delay_multiplier * 1.5)
            else:
                self._delay_multiplier = max(1.0, self._delay_multiplier * 0.9)
        except Exception:
            pass

    def _process_cnpj(
        self, cnpj: str, payload: Dict[str, Any], correlation_id: str
    ) -> bool:
        # idempotency: check DB if already finished
        try:
            if self.db and hasattr(self.db, "get_last_processamento"):
                last = self.db.get_last_processamento(cnpj)
                if last and last.get("state") == "FINALIZADO":
                    log.info(
                        "idempotent-skip", cnpj=cnpj, correlation_id=correlation_id
                    )
                    return True
        except Exception:
            pass

        if not self.locker.acquire(cnpj, timeout=10):
            log.warning("could_not_acquire_lock", cnpj=cnpj)
            return False
        try:
            # resume from checkpoint
            start_step = 1
            try:
                if self.db:
                    last = self.db.get_last_processamento(cnpj)
                    if last and isinstance(last.get("meta"), dict):
                        start_step = int(last.get("meta", {}).get("step", 1))
            except Exception:
                pass

            for step in self.steps[start_step - 1 :]:
                sid = step.get("id")
                try:
                    # persist checkpoint before running
                    if self.db:
                        self.db.record_processamento(
                            cnpj,
                            "PROCESSANDO",
                            json.dumps({"step": sid, "correlation_id": correlation_id}),
                        )
                    res = self._run_step(step, cnpj, payload, correlation_id)
                    if not res:
                        # action per matrix
                        action = step.get("on_failure", "stop")
                        self._apply_failure_action(cnpj, step, correlation_id, action)
                        return False
                except Exception:
                    log.exception(
                        "step_exception",
                        cnpj=cnpj,
                        step=sid,
                        correlation_id=correlation_id,
                    )
                    self._apply_failure_action(cnpj, step, correlation_id, "stop")
                    return False

            # finished
            if self.db:
                self.db.record_processamento(
                    cnpj, "FINALIZADO", json.dumps({"correlation_id": correlation_id})
                )
            return True
        finally:
            self.locker.release(cnpj)

    def _run_step(
        self,
        step: Dict[str, Any],
        cnpj: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> bool:
        sid = step.get("id")
        # allow plugins to handle step
        for p in self.plugins:
            try:
                if hasattr(p, "handle_step") and p.handle_step(
                    step, cnpj, payload, correlation_id
                ):
                    return True
            except Exception:
                log.exception(
                    "plugin_step_failed",
                    plugin=getattr(p, "__name__", "<plugin>"),
                    step=sid,
                )

        # Distinguish between Sintegra/TED (1-23) using pyautogui and SEDIF (24-52) files
        if sid <= 23:
            return self._run_pyauto_step(step, cnpj, payload, correlation_id)
        else:
            return self._run_sedif_step(step, cnpj, payload, correlation_id)

    def _run_pyauto_step(
        self,
        step: Dict[str, Any],
        cnpj: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> bool:
        if not pyautogui:
            log.error("pyautogui_unavailable", correlation_id=correlation_id)
            return False
        selector = step.get("selector")
        # example safe action: move and click
        try:
            # respect delay multiplier
            time.sleep(0.5 * self._delay_multiplier)
            # optional screenshot for integrity
            if step.get("screenshot_on_start"):
                img = pyautogui.screenshot()
                ss_dir = os.path.join(self.base_path, "evidence", cnpj)
                os.makedirs(ss_dir, exist_ok=True)
                path = os.path.join(ss_dir, f"step_{step.get('id')}_start.png")
                img.save(path)
                # compute hash
                try:
                    import hashlib

                    with open(path, "rb") as fh:
                        h = hashlib.sha256(fh.read()).hexdigest()
                    if self.db:
                        self.db.log_audit(
                            "info",
                            "evidence_hash",
                            {"cnpj": cnpj, "step": step.get("id"), "hash": h},
                        )
                except Exception:
                    pass
            # simulate click/typing operations minimally to avoid fragile logic here
            if (
                selector
                and isinstance(selector, dict)
                and selector.get("type") == "click"
            ):
                x = selector.get("x")
                y = selector.get("y")
                pyautogui.moveTo(x, y)
                pyautogui.click()
            if step.get("type") == "type_signature":
                sig = os.getenv("STARK_SIGNATURE", "LEONEL").upper()
                pyautogui.typewrite(sig)
            return True
        except Exception:
            log.exception(
                "pyauto_step_failed", step=step.get("id"), correlation_id=correlation_id
            )
            # attempt popup handling
            self._handle_unexpected_popup(cnpj, step, correlation_id)
            return False

    def _run_sedif_step(
        self,
        step: Dict[str, Any],
        cnpj: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> bool:
        # SEDIF steps operate on .txt files — ensure parser
        try:
            txt_path = payload.get("sedif_txt")
            if not txt_path or not os.path.exists(txt_path):
                log.error(
                    "sedif_missing_file", cnpj=cnpj, correlation_id=correlation_id
                )
                return False
            parsed = self._parse_sedif_txt(txt_path)
            # cross-field validation with payload or screen (best-effort)
            if payload.get("expected_cnpj") and payload.get(
                "expected_cnpj"
            ) != parsed.get("cnpj"):
                log.error(
                    "cross_field_mismatch", cnpj=cnpj, correlation_id=correlation_id
                )
                return False
            # pretend to import: check hash and persist
            import hashlib

            with open(txt_path, "rb") as fh:
                content = fh.read()
                h = hashlib.sha256(content).hexdigest()
            if self.db:
                if self.db.xml_exists_by_hash(h):
                    log.info(
                        "sedif_idempotent_skip",
                        cnpj=cnpj,
                        correlation_id=correlation_id,
                    )
                    return True
                # save_xml_document expects (sha256hex, content_bytes, schema_ok)
                try:
                    self.db.save_xml_document(h, content, schema_ok=True)
                except Exception:
                    try:
                        self.db.save_document(
                            h,
                            txt_path,
                            metadata={"cnpj": cnpj, "correlation_id": correlation_id},
                        )
                    except Exception:
                        pass
            return True
        except Exception:
            log.exception("sedif_step_failed", correlation_id=correlation_id)
            return False

    def _parse_sedif_txt(self, path: str) -> Dict[str, Any]:
        data = {}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    # simple key:value patterns
                    m = re.match(
                        r"\s*(CNPJ|CPF|NOME|IE|IM|DATA)\s*[:=]\s*(.+)$",
                        line.strip(),
                        re.I,
                    )
                    if m:
                        k = m.group(1).strip().lower()
                        v = m.group(2).strip()
                        data[k] = v
        except Exception:
            log.exception("parse_sedif_failed", path=path)
        return data

    def _apply_failure_action(
        self, cnpj: str, step: Dict[str, Any], correlation_id: str, action: str
    ):
        # map actions
        if action == "abort_and_clean":
            self._cleanup_for_cnpj(cnpj)
            if self.db:
                self.db.record_processamento(
                    cnpj, "REJEITADO_FONTE", json.dumps({"step": step.get("id")})
                )
        elif action == "safe_terminate":
            self._safe_terminate_processes(cnpj)
            # will resume from checkpoint on next run
        elif action == "screenshot_and_continue":
            self._capture_screenshot(cnpj, step.get("id"))
        else:
            # default stop
            if self.db:
                self.db.record_processamento(
                    cnpj, "FAILED", json.dumps({"step": step.get("id")})
                )

    def _cleanup_for_cnpj(self, cnpj: str):
        try:
            p = os.path.join(self.base_path, "work", cnpj)
            if os.path.exists(p):
                for root, dirs, files in os.walk(p, topdown=False):
                    for name in files:
                        try:
                            os.remove(os.path.join(root, name))
                        except Exception:
                            pass
                    for name in dirs:
                        try:
                            os.rmdir(os.path.join(root, name))
                        except Exception:
                            pass
                try:
                    os.rmdir(p)
                except Exception:
                    pass
        except Exception:
            log.exception("cleanup_failed", cnpj=cnpj)

    def _safe_terminate_processes(self, cnpj: str):
        # attempt graceful termination of processes that match known legacy names
        try:
            if not psutil:
                return
            names = ["sintegra", "ted", "sedi", "legacyapp"]
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    n = (p.info.get("name") or "").lower()
                    if any(x in n for x in names):
                        try:
                            p.terminate()
                            p.wait(5)
                        except Exception:
                            try:
                                p.kill()
                            except Exception:
                                pass
                except Exception:
                    # ignore per-process inspection errors
                    pass
        except Exception:
            log.exception("safe_terminate_failed", cnpj=cnpj)

    def _capture_screenshot(self, cnpj: str, step_id: int):
        try:
            if not pyautogui:
                return
            img = pyautogui.screenshot()
            ss_dir = os.path.join(self.base_path, "evidence", cnpj)
            os.makedirs(ss_dir, exist_ok=True)
            path = os.path.join(ss_dir, f"step_{step_id}_screenshot.png")
            img.save(path)
            if self.db:
                self.db.log_audit(
                    "info", "screenshot_captured", {"cnpj": cnpj, "step": step_id}
                )
        except Exception:
            log.exception("capture_screenshot_failed", cnpj=cnpj, step=step_id)

    def _handle_unexpected_popup(
        self, cnpj: str, step: Dict[str, Any], correlation_id: str
    ):
        # capture screenshot, try to close topmost windows LIFO
        try:
            self._capture_screenshot(cnpj, step.get("id"))
            # best-effort close using pyautogui
            if pyautogui:
                for i in range(3):
                    pyautogui.press("esc")
                    time.sleep(0.5)
            # log
            if self.db:
                self.db.log_audit(
                    "error",
                    "unexpected_popup",
                    {
                        "cnpj": cnpj,
                        "step": step.get("id"),
                        "correlation_id": correlation_id,
                    },
                )
        except Exception:
            log.exception("popup_handler_failed", cnpj=cnpj)

    def resume_from_checkpoint(self, worker_id: str = None) -> None:
        """Resume processing by re-enqueuing unfinished tasks found in the persistent tasks table.

        This method is safe to be called by external supervisors. It will re-populate the in-memory
        priority queue with PENDENTE/PROCESSANDO/FALHA_RETRY tasks persisted in the DB.
        """
        if not self.db:
            log.warning("resume_requested_but_no_db", worker_id=worker_id)
            return
        try:
            rows = self.db.get_processing_tasks(limit=500)
            for r in rows:
                try:
                    cnpj = r.get("cnpj")
                    payload = {}
                    try:
                        payload = json.loads(r.get("payload") or "{}")
                    except Exception:
                        payload = {"correlation_id": r.get("correlation_id")}
                    # if the DB task isn't PENDENTE, mark it requeued so only one worker handles it
                    state = r.get("state")
                    if state and state != "PENDENTE":
                        try:
                            self.db.requeue_task(int(r.get("id")))
                        except Exception:
                            log.exception(
                                "failed_to_requeue_db_task", task_id=r.get("id")
                            )
                    # attempt to enqueue (in-memory dedupe prevents duplicates)
                    if cnpj:
                        enq = self.enqueue(cnpj, payload)
                        if enq:
                            log.info("resume_enqueued", cnpj=cnpj, worker_id=worker_id)
                        else:
                            log.info(
                                "resume_skipped_already_enqueued",
                                cnpj=cnpj,
                                worker_id=worker_id,
                            )
                except Exception:
                    log.exception("resume_enqueue_failed", worker_id=worker_id)
        except Exception:
            log.exception("resume_from_checkpoint_failed", worker_id=worker_id)


__all__ = ["OperationalLegacyWorker"]
