"""API dos agentes: ``/api/v1/agentes`` (catálogo, uma ação de um agente, ou um plano orquestrado entre vários).

Tudo exige login com a permissão de processar folha, passa pela trilha de auditoria (sem os dados do pedido, só agente, ação e
resultado) e só enxerga o que é da empresa do usuário. Os agentes de verdade ficam em ``contabil_agente/agentes``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from contabil_agente.agentes import (
    AcaoDesconhecida, Agente, AgenteErro, ComplianceAgent, OrquestradorDeAgentes, RPAAgent, ReconciliationAgent, TaxAgent, ValidationAgent,
)
from contabil_agente.security.auth import Principal
from contabil_agente.security.rbac_manager import Permission

from .auth import exigir


class PedidoAcao(BaseModel):
    dados: Dict[str, Any] = Field(default_factory=dict)


class PedidoPlano(BaseModel):
    passos: List[Dict[str, Any]] = Field(min_length=1, max_length=10)


def instalar_agentes(
    app,
    auditar: Callable[..., Optional[str]],
    enfileirar_extrato: Callable[[Request, Principal, str, str, Optional[int]], Dict[str, Any]],
) -> None:
    """Registra as rotas. ``enfileirar_extrato`` é a mesma função das rotas ``/api/v1/rpa/*``: o RPAAgent não duplica a fila."""
    router = APIRouter(prefix="/api/v1/agentes", tags=["agentes"])

    def montar(request: Request, usuario: Principal) -> Dict[str, Agente]:
        def enfileirar(portal: str, documento: str, ano: Optional[int]) -> Dict[str, Any]:
            try:
                return enfileirar_extrato(request, usuario, portal, documento, ano)
            except HTTPException as exc:  # recusa da fila ou da LGPD vira o status do agente, não um erro HTTP solto
                raise AgenteErro(str(exc.detail)) from exc

        def estado(job_id: str) -> Optional[Dict[str, Any]]:
            return request.app.state.rpa_status.obter(job_id, usuario.tenant_id)

        return {a.nome: a for a in (
            TaxAgent(),
            ValidationAgent(),
            ReconciliationAgent(),
            ComplianceAgent(request.app.state.lgpd, usuario.tenant_id),
            RPAAgent(enfileirar, estado),
        )}

    @router.get("")
    def catalogo(request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        return {"agentes": OrquestradorDeAgentes(montar(request, usuario)).catalogo()}

    @router.post("/orquestrar")
    def orquestrar(pedido: PedidoPlano, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        """Roda vários passos em sequência; ``"$N.campo"`` leva o resultado do passo N para o seguinte."""
        try:
            resposta = OrquestradorDeAgentes(montar(request, usuario)).executar(pedido.passos)
        except AgenteErro as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        auditar(request, "process_payroll", usuario, "Plano de agentes executado", passos=[(p["agente"], p["acao"], p["status"]) for p in resposta["passos"]],
                sucesso=resposta["status"] == "ok")
        return resposta

    @router.post("/{agente}/{acao}")
    def executar(agente: str, acao: str, pedido: PedidoAcao, request: Request, usuario: Principal = Depends(exigir(Permission.PROCESS_PAYROLL))):
        agentes = montar(request, usuario)
        alvo = agentes.get(agente)
        if alvo is None:
            raise HTTPException(status_code=404, detail=f"Agente desconhecido. Use: {', '.join(agentes)}.")
        try:
            resposta = alvo.executar(acao, pedido.dados)
        except AcaoDesconhecida as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        auditar(request, "process_payroll", usuario, f"{agente}.{acao}", sucesso=resposta["status"] == "ok", status=resposta["status"])
        return resposta

    app.include_router(router)
