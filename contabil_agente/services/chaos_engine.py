"""Simple chaos engineering scheduler to exercise recovery daily.

This module provides a controlled way to inject small failures into the
system to validate recovery paths. By default it only logs simulated
failures; set `CHAOS_ACTUALLY_KILL`=1 to perform tougher experiments.
"""

import threading
import logging
import os

logger = logging.getLogger("chaos_engine")


class ChaosEngine:
    def __init__(self, interval_seconds: int = 24 * 3600):
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        try:
            self._thread.start()
        except Exception:
            logger.exception("chaos_start_failed")

    def stop(self):
        self._stop.set()
        try:
            self._thread.join(timeout=1)
        except Exception:
            pass

    def _loop(self):
        # simple daily loop; in tests run quicker by setting smaller interval
        while not self._stop.wait(self.interval):
            try:
                self.run_experiment()
            except Exception:
                logger.exception("chaos_experiment_failed")

    def run_experiment(self):
        # Experiment: simulate transient DB connectivity loss and recovery
        logger.info("chaos_experiment start simulated db_disconnect")
        # TODO: integrate with Supervisor to actually cycle a worker when configured
        if os.getenv("CHAOS_ACTUALLY_KILL") == "1":
            logger.warning("chaos: would kill a worker (CHAOS_ACTUALLY_KILL=1 enabled)")
        logger.info("chaos_experiment end simulated db_reconnect")


__all__ = ["ChaosEngine"]
