from __future__ import annotations

from enum import Enum, auto
from typing import Dict, Any
import logging

LOGGER = logging.getLogger("intelligence.fsm")


class State(Enum):
    COLETANDO_CONTEXTO = auto()
    PROCESSANDO = auto()
    AGUARDANDO_INPUT = auto()
    CALCULANDO = auto()
    VALIDANDO = auto()
    FALHA_NA_EXTRACAO = auto()
    FINALIZADO = auto()


class FSM:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = State.COLETANDO_CONTEXTO
        self.history: list[Dict[str, Any]] = []

    def transition(self, to_state: State, reason: str | None = None) -> None:
        LOGGER.info(
            "FSM %s: %s -> %s (%s)",
            self.session_id,
            self.state.name,
            to_state.name,
            reason,
        )
        self.history.append(
            {"from": self.state.name, "to": to_state.name, "reason": reason}
        )
        self.state = to_state

    def is_processing(self) -> bool:
        return self.state == State.PROCESSANDO

    def current(self) -> State:
        return self.state
