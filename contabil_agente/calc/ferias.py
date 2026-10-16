"""Férias gozadas, com 1/3 constitucional e abono pecuniário (venda de até 10 dias)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from .errors import DadosInvalidos
from .inss import calcular_inss
from .irrf import calcular_irrf_mensal
from .money import ZERO, D, nao_negativo, q2


@dataclass(frozen=True)
class ResultadoFerias:
    dias_gozados: int
    dias_vendidos: int
    valor_dias: Decimal
    terco: Decimal
    abono: Decimal
    terco_abono: Decimal
    inss: Decimal
    irrf: Decimal
    bruto: Decimal
    liquido: Decimal
    explicacao: tuple

    def to_dict(self) -> Dict[str, Any]:
        f = lambda x: float(q2(x))  # noqa: E731
        return {
            "status": "success",
            "dias_gozados": self.dias_gozados,
            "dias_vendidos": self.dias_vendidos,
            "valor_dias": f(self.valor_dias),
            "terco_constitucional": f(self.terco),
            "abono_pecuniario": f(self.abono),
            "terco_abono": f(self.terco_abono),
            "inss": f(self.inss),
            "irrf": f(self.irrf),
            "total_bruto": f(self.bruto),
            "total_liquido": f(self.liquido),
            "explicacao": list(self.explicacao),
        }


def calcular_ferias(
    salario_base,
    competencia: date,
    dias_gozados: int = 30,
    dias_vendidos: int = 0,
    adicionais_mensais=0,
    media_variaveis=0,
    dependentes: int = 0,
    caminho_tabelas: Optional[str] = None,
) -> ResultadoFerias:
    """Férias gozadas. O abono pecuniário e o seu 1/3 não sofrem INSS nem IRRF."""
    salario = D(salario_base, "salário base")
    if salario <= 0:
        raise DadosInvalidos("O salário base deve ser maior que zero.")
    rem = salario + nao_negativo(D(adicionais_mensais, "adicionais"), "adicionais") + nao_negativo(
        D(media_variaveis, "média de variáveis"), "média de variáveis"
    )
    if dias_gozados < 0 or dias_vendidos < 0 or dias_vendidos > 10:
        raise DadosInvalidos("Dias de férias inválidos: o abono pecuniário vai de 0 a 10 dias.")
    if dias_gozados + dias_vendidos > 30:
        raise DadosInvalidos("Dias gozados + dias vendidos não podem passar de 30.")
    if dias_gozados == 0:
        raise DadosInvalidos("Informe quantos dias de férias serão gozados.")

    valor_dias = q2(rem / 30 * dias_gozados)
    terco = q2(valor_dias / 3)
    abono = q2(rem / 30 * dias_vendidos)
    terco_abono = q2(abono / 3)
    tributavel = valor_dias + terco

    inss = calcular_inss(tributavel, competencia, caminho_tabelas).valor
    irrf = calcular_irrf_mensal(
        tributavel, competencia, inss=inss, dependentes=dependentes, caminho_tabelas=caminho_tabelas
    ).valor
    bruto = tributavel + abono + terco_abono
    liquido = bruto - inss - irrf
    return ResultadoFerias(
        dias_gozados=dias_gozados,
        dias_vendidos=dias_vendidos,
        valor_dias=valor_dias,
        terco=terco,
        abono=abono,
        terco_abono=terco_abono,
        inss=inss,
        irrf=irrf,
        bruto=bruto,
        liquido=liquido,
        explicacao=(
            f"Férias de {dias_gozados} dias: ({rem} / 30) x {dias_gozados} = {valor_dias}, mais 1/3 = {terco}.",
            f"Abono pecuniário de {dias_vendidos} dias: {abono} + 1/3 = {terco_abono} (isento de INSS e IRRF).",
            f"INSS sobre {tributavel}: {inss}. IRRF: {irrf}.",
        ),
    )
