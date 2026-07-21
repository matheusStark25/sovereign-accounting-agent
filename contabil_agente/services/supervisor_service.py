"""SupervisorService: monitora tarefas em PROCESSANDO que excederam timeout e realiza remediação.

Operação:
- Roda em thread separada
- Procura tasks com state='PROCESSANDO' e started_at older than timeout
- Se owner_pid presente tenta enviar SIGTERM (via psutil if available) e notifica via DatabaseService.notify_alert
- Reseta estado para 'PENDENTE' para reprocessamento
"""

from __future__ import annotations

import threading
import time
import logging
import os
import signal
from typing import Optional

try:
    import psutil
except Exception:
    psutil = None

from contabil_agente.services.database_service import DatabaseService

logger = logging.getLogger("supervisor_service")


class SupervisorService:
    def __init__(self, interval: int = 30, processing_timeout: int = 600):
        try:
            self.db = DatabaseService()
        except Exception:
            self.db = None
        self.interval = interval
        self.processing_timeout = processing_timeout
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="SupervisorService"
        )
        self._callbacks = {}

    def start(self):
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _try_kill(self, pid: int) -> bool:
        try:
            # Defensive checks: never attempt to kill current process, parent,
            # or obviously invalid PIDs. Also avoid killing when running tests
            # (pytest) to prevent test harness interference.
            try:
                import sys

                running_pytest = "pytest" in sys.modules
            except Exception:
                running_pytest = False

            if not isinstance(pid, int) or pid <= 0:
                return False
            current = os.getpid()
            try:
                parent = os.getppid()
            except Exception:
                parent = None

            if pid == current or (parent is not None and pid == parent):
                logger.warning(
                    "SupervisorService: refusing to kill current/parent pid %s", pid
                )
                return False
            if running_pytest or os.getenv("ENABLE_SUPERVISOR") != "1":
                # In test environments or when supervisor not explicitly enabled,
                # do not perform destructive kills.
                logger.info(
                    "SupervisorService: skip kill for pid %s (tests or disabled)", pid
                )
                return False

            if psutil:
                p = psutil.Process(pid)
                p.terminate()
                try:
                    p.wait(timeout=5)
                except Exception:
                    p.kill()
                return True
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                    return True
                except Exception:
                    return False
        except Exception:
            return False

    def register_restart_callback(self, key: str, callback):
        """Register a synchronous callback for restart; key can be worker name or owner pid string."""
        try:
            self._callbacks[str(key)] = callback
        except Exception:
            pass

    def _loop(self):
        while not self._stop.is_set():
            try:
                if not self.db:
                    time.sleep(self.interval)
                    continue
                cutoff = int(time.time()) - self.processing_timeout
                with self.db._transaction() as cur:
                    cur.execute(
                        "SELECT id,cnpj,owner_pid,started_at FROM tasks WHERE state='PROCESSANDO' AND started_at<?",
                        (cutoff,),
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        tid = r["id"]
                        pid = r["owner_pid"]
                        desc = (
                            f"task={tid} cnpj={r['cnpj']} started_at={r['started_at']}"
                        )
                        logger.warning("SupervisorService: stale processing %s", desc)
                        # try kill
                        killed = False
                        if pid:
                            try:
                                killed = self._try_kill(int(pid))
                            except Exception:
                                killed = False

                            # reset task to PENDENTE and increment attempts
                            cur.execute(
                                "UPDATE tasks SET state='PENDENTE', updated_at=? WHERE id=?",
                                (int(time.time()), tid),
                            )
                            try:
                                self.db.notify_alert(
                                    f"Supervisor reset task {tid} (killed={killed}) {desc}"
                                )
                            except Exception:
                                logger.exception("notify_alert failed")

                            # attempt to invoke any registered restart callbacks
                            try:
                                # keys to check: task:<id> and owner:<pid>
                                cb = None
                                if f"task:{tid}" in self._callbacks:
                                    cb = self._callbacks.get(f"task:{tid}")
                                elif pid and str(pid) in self._callbacks:
                                    cb = self._callbacks.get(str(pid))
                                elif f"owner:{pid}" in self._callbacks:
                                    cb = self._callbacks.get(f"owner:{pid}")
                                if cb:
                                    try:
                                        cb(tid)
                                    except Exception:
                                        logger.exception(
                                            "restart callback failed for task %s", tid
                                        )
                            except Exception:
                                logger.exception("error invoking restart callbacks")
            except Exception:
                logger.exception("Supervisor loop error")
            self._stop.wait(self.interval)


_SUP: Optional[SupervisorService] = None


def get_supervisor_service() -> SupervisorService:
    global _SUP
    if _SUP is None:
        _SUP = SupervisorService()
        # Only auto-start the supervisor in explicit environments. This avoids
        # background killers during test runs or when the service is not desired.
        try:
            import sys

            running_pytest = "pytest" in sys.modules
        except Exception:
            running_pytest = False

        if os.getenv("ENABLE_SUPERVISOR") == "1" and not running_pytest:
            _SUP.start()
    return _SUP
