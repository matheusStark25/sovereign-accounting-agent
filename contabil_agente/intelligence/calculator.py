"""TaxEngine: resumo mensal de folha sobre o motor único ``contabil_agente.calc``.

Antes deste módulo havia uma tabela própria (de 2024) e estimativas de FGTS. Agora tudo
vem de ``calc`` (tabelas oficiais versionadas) e nada é estimado.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from contabil_agente.calc import calcular_inss, calcular_irrf_mensal
from contabil_agente.calc.errors import DadosInvalidos
from contabil_agente.calc.money import D, q2
from contabil_agente.calc.tables import tabela_inss, tabela_irrf

_OITO = Decimal("0.08")


def _competencia(valor: Any, hoje: Optional[date]) -> date:
    if valor in (None, ""):
        base = hoje or date.today()
    elif isinstance(valor, datetime):
        base = valor.date()
    elif isinstance(valor, date):
        base = valor
    else:
        try:
            base = datetime.fromisoformat(str(valor)).date()
        except ValueError as exc:
            raise DadosInvalidos(f"data inválida: {valor!r}") from exc
    return date(base.year, base.month, 1)


class TaxEngine:
    """Calcula INSS, IRRF, líquido, FGTS do mês, férias e 13º para um salário."""

    def __init__(self, hoje: Optional[date] = None):
        self.hoje = hoje

    def calculate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """``payload``: ``amount`` (salário), ``date`` (ISO), ``dependentes``, ``meses_trabalhados`` (1-12)."""
        salario = payload.get("amount", payload.get("salario"))
        return self.calcular_trabalhista(salario, payload)

    def calcular_trabalhista(self, salario: Any, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        valor = D(salario, "salário")
        if valor <= 0:
            raise DadosInvalidos("O salário deve ser maior que zero.")
        competencia = _competencia(payload.get("date"), self.hoje)
        dependentes = int(payload.get("dependentes") or 0)
        meses = int(payload.get("meses_trabalhados") or 12)
        if not 1 <= meses <= 12:
            raise DadosInvalidos("meses_trabalhados deve estar entre 1 e 12.")

        inss = calcular_inss(valor, competencia).valor
        irrf = calcular_irrf_mensal(valor, competencia, inss=inss, dependentes=dependentes)
        terco = q2(valor / 3)
        return {
            "salario_bruto": float(q2(valor)),
            "inss": float(inss),
            "irrf": float(irrf.valor),
            "salario_liquido": float(q2(valor - inss - irrf.valor)),
            "fgts_mensal": float(q2(valor * _OITO)),
            "ferias_integral": float(q2(valor + terco)),
            "terco_constitucional": float(terco),
            "decimo_terceiro_proporcional": float(q2(valor / 12 * meses)),
            "meses_considerados_13o": meses,
            "competencia": f"{competencia:%Y-%m}",
            "tabelas": {
                "inss": f"{tabela_inss(competencia).norma} [{tabela_inss(competencia).verificacao}]",
                "irrf": f"{tabela_irrf(competencia).norma} [{tabela_irrf(competencia).verificacao}]",
            },
        }
