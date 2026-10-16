"""Operator shield: monitors input dynamics and detects stress/coercion.

Enhancements:
- uses `pyautogui` to sample mouse movement timings and `psutil` for process info
- computes latency variance and triggers stress protocol if variance > 40%

Note: this module collects aggregated timing metrics only.
"""

import threading
import time
import statistics
import logging
import json
from typing import Dict

logger = logging.getLogger("operator_shield")

try:
    import pyautogui
except Exception:
    logger.exception("operator_shield_deps_missing")
    raise RuntimeError("operator_shield dependencies missing; failing safe")


class OperatorShield:
    def __init__(self, sample_interval: float = 5.0, sample_rate: float = 0.05):
        self.sample_interval = sample_interval
        self.sample_rate = sample_rate
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._metrics = {"mouse_move_intervals": [], "last_sample": time.time()}

    def start(self):
        try:
            self._thread.start()
        except Exception:
            logger.exception("shield_start_failed")

    def stop(self):
        self._stop.set()
        try:
            self._thread.join(timeout=1)
        except Exception:
            pass

    def _sample_input_intervals(self, duration: float):
        """Sample mouse positions and produce list of inter-move intervals in seconds."""
        intervals = []
        last_pos = pyautogui.position()
        last_time = time.time()
        end = time.time() + duration
        while time.time() < end and not self._stop.is_set():
            time.sleep(self.sample_rate)
            pos = pyautogui.position()
            now = time.time()
            if pos != last_pos:
                intervals.append(now - last_time)
                last_pos = pos
                last_time = now
        return intervals

    def _compute_stress(self, intervals: list) -> float:
        try:
            if not intervals:
                return 0.0
            mean = statistics.mean(intervals)
            stdev = statistics.pstdev(intervals)
            # relative variance
            rel = (stdev / mean) if mean > 0 else 0.0
            # map rel into [0..1]
            s = min(1.0, rel)
            return s
        except Exception:
            logger.exception("compute_stress_failed")
            return 0.0

    def _protocol_stress(self, metrics: Dict):
        # Placeholder for triggering stress-handling protocol
        logger.warning(
            json.dumps(
                {"event": "operator_stress_triggered", "metrics": metrics},
                ensure_ascii=False,
            )
        )

    def _loop(self):
        while not self._stop.wait(self.sample_interval):
            try:
                intervals = self._sample_input_intervals(self.sample_interval)
                stress = self._compute_stress(intervals)
                snapshot = {"samples": len(intervals), "stress": stress}
                logger.info(
                    json.dumps(
                        {"event": "operator_shield_sample", "snapshot": snapshot},
                        ensure_ascii=False,
                    )
                )
                if stress > 0.4:
                    self._protocol_stress(snapshot)
            except Exception:
                logger.exception("operator_shield_loop_error")


__all__ = ["OperatorShield"]
