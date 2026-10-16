"""Resiliência: disjuntor, retry com backoff exponencial, timeout e degradação elegante."""

from .circuit import CircuitBreaker, CircuitoAberto, Estado
from .degradacao import ChamadaResiliente
from .retry import calcular_atraso, com_retry, com_retry_async
from .timeouts import TimeoutExcedido, com_timeout

__all__ = [
    "CircuitBreaker",
    "CircuitoAberto",
    "Estado",
    "ChamadaResiliente",
    "calcular_atraso",
    "com_retry",
    "com_retry_async",
    "TimeoutExcedido",
    "com_timeout",
]
