from __future__ import annotations

import asyncio
import contextvars
from typing import Any, Callable


async def async_run_in_executor(fn: Callable[..., Any], *args, executor=None) -> Any:
    """Run function in executor while preserving contextvars (e.g., correlation_id).

    Usage: await async_run_in_executor(blocking_fn, arg1, arg2)
    """
    loop = asyncio.get_event_loop()
    ctx = contextvars.copy_context()

    def _run():
        return ctx.run(fn, *args)

    return await loop.run_in_executor(executor, _run)
