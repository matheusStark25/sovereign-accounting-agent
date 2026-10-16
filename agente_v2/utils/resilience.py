from __future__ import annotations
import asyncio
import time
from typing import Callable
from typing import Coroutine
from typing import Optional


class CircuitOpen(Exception):
    pass


class CircuitBreaker:
    def __init__(
        self,
        max_failures: int = 5,
        reset_timeout: float = 30.0,
        name: str | None = None,
    ):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: Optional[float] = None
        self.name = name or "circuit"
        # optional prometheus counters
        try:
            from prometheus_client import Counter

            self._metric_failures = Counter(
                f"{self.name}_failures_total", f"Failures for {self.name}"
            )
            self._metric_open = Counter(
                f"{self.name}_open_total", f"Times circuit opened for {self.name}"
            )
        except Exception:
            self._metric_failures = None
            self._metric_open = None

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._metric_failures is not None:
            try:
                self._metric_failures.inc()
            except Exception:
                pass
        if self._failures >= self.max_failures and self._opened_at is None:
            self._opened_at = time.time()
            if self._metric_open is not None:
                try:
                    self._metric_open.inc()
                except Exception:
                    pass

    def closed(self) -> bool:
        if self._opened_at is None:
            return True
        if (time.time() - self._opened_at) >= self.reset_timeout:
            # allow trial
            self._failures = 0
            self._opened_at = None
            return True
        return False


async def retry_backoff(
    func: Callable[..., Coroutine],
    *args,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    **kwargs,
):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last = exc
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            await asyncio.sleep(delay)
    raise last
