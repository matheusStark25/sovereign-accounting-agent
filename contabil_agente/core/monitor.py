from __future__ import annotations
import time
import threading
from typing import Dict


class MetricsCollector:
    """Simple metrics collector prepared for Prometheus export.

    Tracks counts for successes/failures and running average latency.
    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {"success": 0, "failure": 0}
        self._latency_sum = 0.0
        self._latency_count = 0

    def inc_success(self) -> None:
        with self._lock:
            self._counters["success"] += 1

    def inc_failure(self) -> None:
        with self._lock:
            self._counters["failure"] += 1

    def observe_latency(self, seconds: float) -> None:
        with self._lock:
            self._latency_sum += seconds
            self._latency_count += 1

    def latency_media(self) -> float:
        with self._lock:
            if self._latency_count == 0:
                return 0.0
            return self._latency_sum / self._latency_count

    def get_metrics(self) -> Dict[str, float]:
        with self._lock:
            return {
                "success": self._counters["success"],
                "failure": self._counters["failure"],
                "latencia_media": self.latency_media(),
            }


class Timer:
    """Context manager to measure latency and feed metrics."""

    def __init__(self, metrics: MetricsCollector) -> None:
        self.metrics = metrics

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = time.perf_counter() - self._start
        self.metrics.observe_latency(elapsed)
