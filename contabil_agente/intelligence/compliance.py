"""ComplianceChecker: regras de conformidade sobre os dados e sobre o resultado do cálculo.

As regras vêm de ``rules/compliance_rules.yaml``; o salário mínimo vem das tabelas oficiais
(``calc/data/tabelas.json``), sem repetir valor.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from contabil_agente.calc.errors import CalculoError, CompetenciaSemTabela
from contabil_agente.calc.money import D
from contabil_agente.calc.tables import tabela_inss
from contabil_agente.utils.documentos import cpf_valido, so_digitos

LOGGER = logging.getLogger("intelligence.compliance")
_REGRAS_PADRAO = Path(__file__).resolve().parents[2] / "rules" / "compliance_rules.yaml"


class ComplianceChecker:
    def __init__(self, rules_path: Optional[str] = None):
        self.rules_path = Path(rules_path) if rules_path else _REGRAS_PADRAO
        with open(self.rules_path, "r", encoding="utf-8") as fh:  # falha alto: sem regras não há compliance
            self.rules = yaml.safe_load(fh) or {}

    def validate(self, data: Dict[str, Any], calculo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Devolve ``{"ok": bool, "issues": [...], "alerts": [...]}``.

        ``issues`` bloqueiam; ``alerts`` pedem revisão humana.
        """
        issues: List[Dict[str, str]] = []
        alerts: List[Dict[str, str]] = []
        geral = self.rules.get("general", {})
        integridade = self.rules.get("integrity", {})

        cpf = data.get("cpf") or data.get("cp")
        if cpf and not cpf_valido(cpf):
            issues.append({"field": "cpf", "issue": f"CPF inválido ({so_digitos(cpf)[:3]}...)"})

        salario = data.get("salario") or data.get("salario_base") or data.get("amount")
        if salario not in (None, "", 0):
            try:
                valor = D(salario, "salário")
                competencia = _competencia(data)
                if integridade.get("minimum_wage_enforcement") and competencia:
                    minimo = tabela_inss(competencia).salario_minimo
                    if valor < minimo:
                        issues.append({"field": "salario", "issue": f"abaixo do salário mínimo de {minimo}"})
            except CompetenciaSemTabela as exc:
                alerts.append({"field": "salario", "issue": f"salário mínimo não verificado: {exc}"})
            except CalculoError as exc:
                issues.append({"field": "salario", "issue": str(exc)})

        if calculo:
            liquido = calculo.get("total_liquido", calculo.get("salario_liquido"))
            if integridade.get("block_negative_net_pay") and liquido is not None and liquido < 0:
                issues.append({"field": "liquido", "issue": "líquido negativo (descontos superam proventos)"})
            proventos = calculo.get("total_proventos") or calculo.get("total_bruto")
            descontos = calculo.get("total_descontos")
            limite = geral.get("max_discount_total")
            if proventos and descontos is not None and limite:
                if D(descontos, "descontos") > D(proventos, "proventos") * D(limite) / 100:
                    alerts.append({"field": "descontos", "issue": f"descontos acima de {limite}% dos proventos"})
            alvo = self.rules.get("audit", {}).get("alert_threshold_termination")
            if calculo.get("tipo") and proventos and alvo and D(proventos, "proventos") > D(alvo):
                alerts.append({"field": "rescisao", "issue": f"rescisão acima de R$ {alvo}: revisão humana recomendada"})
        return {"ok": not issues, "issues": issues, "alerts": alerts}


def _competencia(data: Dict[str, Any]) -> Optional[date]:
    bruto = data.get("data_demissao") or data.get("competencia") or data.get("date")
    if not bruto:
        return date.today().replace(day=1)
    try:
        return datetime.fromisoformat(str(bruto)).date().replace(day=1)
    except ValueError:
        return None
