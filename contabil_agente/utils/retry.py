from __future__ import annotations
import time
import functools
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def retry(max_attempts: int = 3, base_delay: float = 0.5):
    """Decorator implementing exponential backoff retries.

    Usage: @retry(max_attempts=3, base_delay=0.5)
    """

    def deco(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    sleep = base_delay * (2 ** (attempt - 1))
                    time.sleep(sleep)

        return wrapper  # type: ignore

    return deco
