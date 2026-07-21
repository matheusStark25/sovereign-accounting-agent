from __future__ import annotations

import time
from enum import Enum, auto
import threading


class State(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreakerV2:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 30):
        self._state = State.CLOSED
        self._failures = 0
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._state = State.CLOSED
            self._opened_at = None

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._state = State.OPEN
                self._opened_at = time.time()

    def allow(self) -> bool:
        with self._lock:
            if self._state == State.CLOSED:
                return True
            if self._state == State.OPEN:
                if (
                    self._opened_at
                    and (time.time() - self._opened_at) > self._reset_timeout
                ):
                    self._state = State.HALF_OPEN
                    return True
                return False
            if self._state == State.HALF_OPEN:
                return True
        return False
