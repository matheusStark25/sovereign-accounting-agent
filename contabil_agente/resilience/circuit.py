"""Disjuntor (circuit breaker) com limiares configuráveis, seguro entre threads.

Estados: ``FECHADO`` (chamadas passam), ``ABERTO`` (chamadas recusadas por ``janela_reset`` segundos
depois de ``limite_falhas`` falhas seguidas) e ``MEIO_ABERTO`` (depois da janela, deixa passar UMA
chamada de teste: se der certo fecha; se falhar, reabre).
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Any, Callable, Optional, Tuple, Type


class Estado(Enum):
    FECHADO = "fechado"
    ABERTO = "aberto"
    MEIO_ABERTO = "meio_aberto"


class CircuitoAberto(RuntimeError):
    """A chamada foi recusada porque o disjuntor está aberto."""

    def __init__(self, nome: str, espera: float):
        super().__init__(f"Disjuntor '{nome}' aberto: tente de novo em {espera:.0f}s.")
        self.nome, self.espera = nome, espera


class CircuitBreaker:
    def __init__(
        self,
        nome: str = "circuito",
        limite_falhas: int = 5,
        janela_reset: float = 30.0,
        excecoes: Tuple[Type[BaseException], ...] = (Exception,),
        relogio: Callable[[], float] = time.monotonic,
    ):
        if limite_falhas < 1 or janela_reset < 0:
            raise ValueError("limite_falhas deve ser >= 1 e janela_reset >= 0.")
        self.nome, self.limite_falhas, self.janela_reset = nome, limite_falhas, janela_reset
        self.excecoes = excecoes
        self._relogio = relogio
        self._lock = threading.Lock()
        self._estado = Estado.FECHADO
        self._falhas = 0
        self._aberto_em: Optional[float] = None
        self._teste_em_andamento = False
        self.total_chamadas = self.total_falhas = self.total_recusadas = 0

    @property
    def estado(self) -> Estado:
        with self._lock:
            self._atualizar()
            return self._estado

    def _atualizar(self) -> None:
        if self._estado is Estado.ABERTO and self._relogio() - (self._aberto_em or 0) >= self.janela_reset:
            self._estado = Estado.MEIO_ABERTO
            self._teste_em_andamento = False

    def _permitir(self) -> None:
        with self._lock:
            self._atualizar()
            if self._estado is Estado.ABERTO:
                self.total_recusadas += 1
                raise CircuitoAberto(self.nome, max(0.0, self.janela_reset - (self._relogio() - (self._aberto_em or 0))))
            if self._estado is Estado.MEIO_ABERTO:
                if self._teste_em_andamento:
                    self.total_recusadas += 1
                    raise CircuitoAberto(self.nome, 0.0)
                self._teste_em_andamento = True

    def registrar_sucesso(self) -> None:
        with self._lock:
            self._falhas = 0
            self._estado = Estado.FECHADO
            self._aberto_em = None
            self._teste_em_andamento = False

    def registrar_falha(self) -> None:
        with self._lock:
            self.total_falhas += 1
            self._falhas += 1
            if self._estado is Estado.MEIO_ABERTO or self._falhas >= self.limite_falhas:
                self._estado = Estado.ABERTO
                self._aberto_em = self._relogio()
                self._teste_em_andamento = False

    def chamar(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self._permitir()
        self.total_chamadas += 1
        try:
            resultado = func(*args, **kwargs)
        except self.excecoes:
            self.registrar_falha()
            raise
        except BaseException:
            # erro que não conta como falha do serviço (ex.: KeyboardInterrupt): libera o teste
            with self._lock:
                self._teste_em_andamento = False
            raise
        self.registrar_sucesso()
        return resultado

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Uso como decorador: ``@breaker``."""

        def envolvida(*args: Any, **kwargs: Any) -> Any:
            return self.chamar(func, *args, **kwargs)

        envolvida.__name__ = getattr(func, "__name__", "envolvida")
        return envolvida

    def estatisticas(self) -> dict:
        return {
            "nome": self.nome,
            "estado": self.estado.value,
            "falhas_seguidas": self._falhas,
            "chamadas": self.total_chamadas,
            "falhas": self.total_falhas,
            "recusadas": self.total_recusadas,
        }
