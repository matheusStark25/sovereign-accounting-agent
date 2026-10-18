"""Chamada resiliente: disjuntor + timeout + retry + degradação elegante (fallback)."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple, Type, TypeVar

from .circuit import CircuitBreaker, CircuitoAberto
from .retry import com_retry
from .timeouts import com_timeout

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ChamadaResiliente:
    """Envolve uma dependência externa. Sem ``fallback`` a falha final é levantada; com ele, a resposta degrada."""

    def __init__(
        self,
        nome: str,
        limite_falhas: int = 5,
        janela_reset: float = 30.0,
        timeout: Optional[float] = 20.0,
        tentativas: int = 3,
        atraso_inicial: float = 0.5,
        excecoes: Tuple[Type[BaseException], ...] = (Exception,),
        disjuntor: Optional[CircuitBreaker] = None,
        dormir: Optional[Callable[[float], None]] = None,
        nao_repetir: Tuple[Type[BaseException], ...] = (),
    ):
        self.nome = nome
        self.disjuntor = disjuntor or CircuitBreaker(nome, limite_falhas, janela_reset, excecoes)
        self.timeout, self.tentativas, self.atraso_inicial, self.excecoes = timeout, tentativas, atraso_inicial, excecoes
        self._dormir = dormir
        self._nao_repetir = tuple(nao_repetir)  # falhas em que tentar de novo só piora (ex.: o portal bloqueou o robô)

    def _uma_tentativa(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if self.timeout:
            return self.disjuntor.chamar(lambda: com_timeout(func, self.timeout, *args, **kwargs))
        return self.disjuntor.chamar(func, *args, **kwargs)

    def chamar(
        self, func: Callable[..., T], *args: Any, fallback: Optional[Callable[[BaseException], T]] = None, **kwargs: Any
    ) -> T:
        extra = {"dormir": self._dormir} if self._dormir else {}
        try:
            return com_retry(
                self._uma_tentativa, func, *args,
                tentativas=self.tentativas, atraso_inicial=self.atraso_inicial,
                excecoes=self.excecoes, nao_repetir=(CircuitoAberto,) + self._nao_repetir, **extra, **kwargs,
            )
        except BaseException as exc:
            if fallback is None or not isinstance(exc, self.excecoes + (CircuitoAberto,)):
                raise
            logger.warning("%s indisponível (%s): usando alternativa.", self.nome, type(exc).__name__)
            return fallback(exc)
