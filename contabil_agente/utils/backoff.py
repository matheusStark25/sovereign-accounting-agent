from __future__ import annotations

import random


def full_jitter_sleep(base: float, attempt: int, cap: float = 30.0) -> float:
    """Compute sleep interval using full jitter exponential backoff.

    Returns seconds to sleep (caller should await/sleep).
    """
    exp = min(cap, base * (2**attempt))
    return random.random() * exp
