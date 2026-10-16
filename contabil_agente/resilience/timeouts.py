"""Timeout portátil (Windows, Linux e threads): a chamada roda numa thread auxiliar.

Limite: o Python não mata a thread; se a função travar ela continua em segundo plano até terminar.
Para chamadas de rede prefira o timeout do próprio cliente (httpx etc.) e use este como rede de segurança.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturoTimeout
from typing import Any, Callable, TypeVar

T = TypeVar("T")
_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="timeout")


class TimeoutExcedido(TimeoutError):
    pass


def com_timeout(func: Callable[..., T], segundos: float, *args: Any, **kwargs: Any) -> T:
    futuro = _EXECUTOR.submit(func, *args, **kwargs)
    try:
        return futuro.result(timeout=segundos)
    except _FuturoTimeout:
        futuro.cancel()
        raise TimeoutExcedido(f"A chamada passou de {segundos:g}s.") from None
