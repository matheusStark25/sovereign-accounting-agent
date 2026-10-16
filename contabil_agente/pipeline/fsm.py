"""Máquina de estados do processamento de documentos (7 estados).

    RECEIVED -> CLASSIFYING -> PROCESSING -> REVIEWING -> CORRECTING -> DISPATCHING -> ARCHIVED

O caminho feliz pode pular CORRECTING (REVIEWING -> DISPATCHING quando não há o que corrigir) e a
correção volta à revisão (CORRECTING -> REVIEWING) até o limite de rodadas. Não existe estado de
erro: se uma etapa falha, a máquina fica parada no estado em que estava e ``falha`` guarda o motivo.
Só ``ARCHIVED`` significa "processado e arquivado".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, FrozenSet, List, Optional


class Estado(Enum):
    RECEIVED = "RECEIVED"
    CLASSIFYING = "CLASSIFYING"
    PROCESSING = "PROCESSING"
    REVIEWING = "REVIEWING"
    CORRECTING = "CORRECTING"
    DISPATCHING = "DISPATCHING"
    ARCHIVED = "ARCHIVED"


TRANSICOES: Dict[Estado, FrozenSet[Estado]] = {
    Estado.RECEIVED: frozenset({Estado.CLASSIFYING}),
    Estado.CLASSIFYING: frozenset({Estado.PROCESSING}),
    Estado.PROCESSING: frozenset({Estado.REVIEWING}),
    Estado.REVIEWING: frozenset({Estado.CORRECTING, Estado.DISPATCHING}),
    Estado.CORRECTING: frozenset({Estado.REVIEWING, Estado.DISPATCHING}),
    Estado.DISPATCHING: frozenset({Estado.ARCHIVED}),
    Estado.ARCHIVED: frozenset(),
}


class TransicaoInvalida(RuntimeError):
    pass


@dataclass
class Passo:
    de: Optional[Estado]
    para: Estado
    em: float
    motivo: str = ""


@dataclass
class MaquinaDeEstados:
    estado: Estado = Estado.RECEIVED
    historico: List[Passo] = field(default_factory=list)
    falha: Optional[str] = None
    estado_da_falha: Optional[Estado] = None
    relogio: Callable[[], float] = time.time
    ao_transitar: Optional[Callable[[Passo], None]] = None

    def __post_init__(self) -> None:
        self.historico.append(Passo(None, self.estado, self.relogio(), "documento recebido"))

    def transitar(self, para: Estado, motivo: str = "") -> Passo:
        if self.falha is not None:
            raise TransicaoInvalida(f"A máquina falhou em {self.estado_da_falha.value}: {self.falha}")
        if para not in TRANSICOES[self.estado]:
            raise TransicaoInvalida(f"Transição inválida: {self.estado.value} -> {para.value}.")
        passo = Passo(self.estado, para, self.relogio(), motivo)
        self.estado = para
        self.historico.append(passo)
        if self.ao_transitar is not None:
            self.ao_transitar(passo)
        return passo

    def falhar(self, motivo: str) -> None:
        self.falha = motivo
        self.estado_da_falha = self.estado

    @property
    def concluida(self) -> bool:
        return self.estado is Estado.ARCHIVED and self.falha is None

    def caminho(self) -> List[str]:
        return [p.para.value for p in self.historico]
