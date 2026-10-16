"""IntelligenceOrchestrator: coleta contexto, valida, calcula (motor real) e audita.

Fluxo (FSM): COLETANDO_CONTEXTO -> PROCESSANDO -> VALIDANDO -> CALCULANDO -> FINALIZADO.
Dados faltando ou inválidos levam a AGUARDANDO_INPUT com a lista do que falta; erros de
cálculo viram ``status = "error"`` com a mensagem, nunca um zero silencioso.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from typing import Any, Dict, Optional

from contabil_agente.calc import servico
from contabil_agente.calc.errors import CalculoError
from contabil_agente.calc.servico import TIPOS_CALCULO

from .audit import ForensicAudit
from .cache import CacheDB
from .calculator import TaxEngine
from .compliance import ComplianceChecker
from .fsm import FSM, State

LOGGER = logging.getLogger("intelligence.orchestrator")


def mesclar_fontes(fontes: list) -> Dict[str, Any]:
    """Une dados de várias fontes: maior peso vence; em empate, a mais recente."""
    escolhido: Dict[str, Dict[str, Any]] = {}
    for fonte in fontes or []:
        peso = fonte.get("weight", 0)
        instante = fonte.get("timestamp") or 0
        for chave, valor in (fonte.get("data") or {}).items():
            atual = escolhido.get(chave)
            if atual is None or (peso, instante) > (atual["peso"], atual["instante"]):
                escolhido[chave] = {"valor": valor, "peso": peso, "instante": instante}
    return {k: v["valor"] for k, v in escolhido.items()}


class IntelligenceOrchestrator:
    def __init__(self, db_path: Optional[str] = None, hoje: Optional[date] = None):
        self.cache = CacheDB(db_path)
        self.engine = TaxEngine(hoje)
        self.compliance = ComplianceChecker()
        self.audit = ForensicAudit()
        self.hoje = hoje
        self._locks: Dict[str, asyncio.Lock] = {}

    async def handle(self, session_id: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise RuntimeError("session processing in progress")
        async with lock:
            return await asyncio.wait_for(asyncio.to_thread(self._processar, session_id, payload), timeout)

    # ------------------------------------------------------------------
    def _processar(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        fsm = FSM(session_id)
        fsm.transition(State.PROCESSANDO, "inicio")
        request_id = str(uuid.uuid4())

        fsm.transition(State.COLETANDO_CONTEXTO)
        dados = mesclar_fontes(payload.get("sources", []))
        for chave in ("amount", "salario", "date"):
            if payload.get(chave) not in (None, "", 0) and chave not in dados:
                dados[chave] = payload[chave]
        self.cache.set(session_id, {"final_data": dados}, ttl_seconds=3600)

        fsm.transition(State.VALIDANDO, "conformidade dos dados")
        comp = self.compliance.validate(dados)
        if not comp["ok"]:
            fsm.transition(State.FALHA_NA_EXTRACAO, "; ".join(i["issue"] for i in comp["issues"]))
            fsm.transition(State.AGUARDANDO_INPUT, "corrigir dados")
            return self._finalizar(request_id, session_id, dados, fsm, {"status": "needs_manual_input", "issues": comp["issues"], "comp": comp})

        fsm.transition(State.CALCULANDO)
        tipo = payload.get("tipo_calculo")
        calc: Optional[Dict[str, Any]] = None
        try:
            if tipo in TIPOS_CALCULO:
                resposta = servico.calcular(tipo, dados, hoje=self.hoje)
                if resposta["status"] == "faltam_dados":
                    fsm.transition(State.AGUARDANDO_INPUT, "faltam dados")
                    return self._finalizar(request_id, session_id, dados, fsm, {
                        "status": "needs_manual_input", "faltando": resposta["faltando"],
                        "pergunta": resposta["pergunta"], "comp": comp})
                if resposta["status"] == "erro":
                    fsm.transition(State.FALHA_NA_EXTRACAO, resposta["mensagem"])
                    return self._finalizar(request_id, session_id, dados, fsm, {
                        "status": "error", "error": resposta["mensagem"], "comp": comp})
                calc = dict(resposta["resultado"], tipo=tipo, resumo=resposta["resumo"])
            elif dados.get("amount") or dados.get("salario"):
                calc = self.engine.calculate(dados)
        except CalculoError as exc:
            fsm.transition(State.FALHA_NA_EXTRACAO, str(exc))
            return self._finalizar(request_id, session_id, dados, fsm, {"status": "error", "error": str(exc), "comp": comp})

        comp = self.compliance.validate(dados, calc)
        fsm.transition(State.FINALIZADO, "concluido")
        return self._finalizar(request_id, session_id, dados, fsm, {"status": "ok", "calc": calc, "comp": comp})

    def _finalizar(self, request_id, session_id, dados, fsm, resultado: Dict[str, Any]) -> Dict[str, Any]:
        self.audit.record(
            request_id=request_id,
            session_id=session_id,
            input_sanitized=dados,
            output={k: v for k, v in resultado.items() if k != "calc"} | {"calc_ok": resultado.get("calc") is not None},
        )
        return {"request_id": request_id, "fsm": fsm.history, **resultado}
