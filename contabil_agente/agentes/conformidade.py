"""ComplianceAgent: regras de conformidade (``rules/compliance_rules.yaml``) e base legal da LGPD para cada finalidade."""

from __future__ import annotations

from typing import Any, Dict, Optional

from contabil_agente.intelligence.compliance import ComplianceChecker
from contabil_agente.lgpd import FINALIDADES, ServicoLGPD, TratamentoSemBaseLegal

from .base import Agente, AgenteErro, exigir_campo


class ComplianceAgent(Agente):
    nome = "ComplianceAgent"
    descricao = (
        "Aplica as regras de conformidade aos dados e ao resultado de um cálculo (CPF válido, salário mínimo da competência, "
        "líquido negativo, descontos altos) e diz se há base legal da LGPD para tratar os dados para uma finalidade."
    )

    def __init__(self, lgpd: Optional[ServicoLGPD] = None, tenant: str = "default", checker: Optional[ComplianceChecker] = None):
        self.lgpd, self.tenant = lgpd, tenant
        self._checker = checker

    @property
    def checker(self) -> ComplianceChecker:
        if self._checker is None:
            self._checker = ComplianceChecker()
        return self._checker

    def acao_verificar(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Confere ``{"dados": {...}, "calculo": {...} opcional}``: ``issues`` bloqueiam, ``alerts`` pedem revisão."""
        entrada = exigir_campo(dados, "dados", dict)
        calculo = dados.get("calculo")
        if calculo is not None and not isinstance(calculo, dict):
            raise AgenteErro("O campo 'calculo' precisa ser um objeto.")
        r = self.checker.validate(entrada, calculo)
        return {"conforme": r["ok"], "issues": r["issues"], "alerts": r["alerts"]}

    def acao_base_legal(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Diz se há base legal para uma finalidade: ``{"finalidade": "calculo_trabalhista", "titular": "CPF" opcional}``."""
        if self.lgpd is None:
            raise AgenteErro("Serviço de LGPD não disponível neste contexto.")
        codigo = exigir_campo(dados, "finalidade", str)
        if codigo not in FINALIDADES:
            return {"permitido": False, "motivo": f"Finalidade não cadastrada: {codigo!r}.", "finalidades": sorted(FINALIDADES)}
        try:
            base = self.lgpd.exigir_base_legal(codigo, self.tenant, dados.get("titular"))
        except TratamentoSemBaseLegal as exc:
            return {"permitido": False, "motivo": str(exc), "dados_sensiveis": FINALIDADES[codigo].dados_sensiveis}
        return {"permitido": True, "base_legal": base, "dados_sensiveis": FINALIDADES[codigo].dados_sensiveis}

    def acao_finalidades(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Lista as finalidades cadastradas e a base legal de cada uma."""
        return {"finalidades": [{"codigo": f.codigo, "descricao": f.descricao, "base_legal": f.base.value} for f in FINALIDADES.values()]}
