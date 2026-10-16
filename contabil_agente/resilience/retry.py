"""Nova tentativa com backoff exponencial e jitter (síncrona e assíncrona)."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, Tuple, Type, TypeVar

T = TypeVar("T")


def calcular_atraso(tentativa: int, inicial: float, fator: float, maximo: float, jitter: float) -> float:
    """Atraso depois da falha de número ``tentativa`` (1ª falha = 1): inicial x fator^(n-1), limitado, com jitter."""
    base = min(maximo, inicial * (fator ** (tentativa - 1)))
    return base * (1 + random.uniform(-jitter, jitter)) if jitter else base


def com_retry(
    func: Callable[..., T],
    *args: Any,
    tentativas: int = 3,
    atraso_inicial: float = 0.5,
    fator: float = 2.0,
    atraso_maximo: float = 8.0,
    jitter: float = 0.2,
    excecoes: Tuple[Type[BaseException], ...] = (Exception,),
    nao_repetir: Tuple[Type[BaseException], ...] = (),
    dormir: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> T:
    """Chama ``func``; em ``excecoes`` espera (backoff exponencial) e tenta de novo, até ``tentativas``."""
    if tentativas < 1:
        raise ValueError("tentativas deve ser >= 1.")
    for n in range(1, tentativas + 1):
        try:
            return func(*args, **kwargs)
        except nao_repetir:
            raise
        except excecoes:
            if n == tentativas:
                raise
            dormir(calcular_atraso(n, atraso_inicial, fator, atraso_maximo, jitter))
    raise AssertionError("inalcançável")


async def com_retry_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    tentativas: int = 3,
    atraso_inicial: float = 0.5,
    fator: float = 2.0,
    atraso_maximo: float = 8.0,
    jitter: float = 0.2,
    excecoes: Tuple[Type[BaseException], ...] = (Exception,),
    nao_repetir: Tuple[Type[BaseException], ...] = (),
    dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    **kwargs: Any,
) -> T:
    if tentativas < 1:
        raise ValueError("tentativas deve ser >= 1.")
    for n in range(1, tentativas + 1):
        try:
            return await func(*args, **kwargs)
        except nao_repetir:
            raise
        except excecoes:
            if n == tentativas:
                raise
            await dormir(calcular_atraso(n, atraso_inicial, fator, atraso_maximo, jitter))
    raise AssertionError("inalcançável")
