from __future__ import annotations

import time
import threading
from typing import Callable, Optional


class CircuitBreaker:
    def __init__(self, max_failures: int = 5, reset_timeout: int = 60):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._state = "CLOSED"
        self._lock = threading.Lock()
        self._opened_at: Optional[float] = None

    def call(self, fn: Callable, *args, **kwargs):
        with self._lock:
            if self._state == "OPEN":
                if time.time() - (self._opened_at or 0) > self.reset_timeout:
                    self._state = "HALF_OPEN"
                else:
                    raise RuntimeError("circuit_open")
        try:
            res = fn(*args, **kwargs)
        except Exception:
            with self._lock:
                self._failures += 1
                if self._failures >= self.max_failures:
                    self._state = "OPEN"
                    self._opened_at = time.time()
            raise
        else:
            with self._lock:
                self._failures = 0
                self._state = "CLOSED"
            return res
