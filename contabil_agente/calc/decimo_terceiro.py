"""13º salário: 1ª parcela (50%, sem descontos) e 2ª parcela (saldo menos INSS e IRRF).

INSS e IRRF incidem sobre o valor total do 13º, separados da folha do mês
(IRRF exclusivo na fonte, com a redução da Lei 15.270/2025, art. 3º-A, §3º).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from .errors import DadosInvalidos
from .inss import calcular_inss
from .irrf import calcular_irrf_mensal
from .money import D, nao_negativo, q2


@dataclass(frozen=True)
class ResultadoDecimoTerceiro:
    meses: int
    total_bruto: Decimal
    primeira_parcela: Decimal
    inss: Decimal
    irrf: Decimal
    segunda_parcela: Decimal
    explicacao: tuple

    def to_dict(self) -> Dict[str, Any]:
        f = lambda x: float(q2(x))  # noqa: E731
        return {
            "status": "success",
            "meses": self.meses,
            "total_bruto": f(self.total_bruto),
            "primeira_parcela": f(self.primeira_parcela),
            "inss": f(self.inss),
            "irrf": f(self.irrf),
            "segunda_parcela": f(self.segunda_parcela),
            "total_liquido": f(self.primeira_parcela + self.segunda_parcela),
            "explicacao": list(self.explicacao),
        }


def calcular_decimo_terceiro(
    salario_base,
    meses: int,
    competencia: date,
    adicionais_mensais=0,
    media_variaveis=0,
    dependentes: int = 0,
    adiantamento=None,
    caminho_tabelas: Optional[str] = None,
) -> ResultadoDecimoTerceiro:
    """Calcula o 13º para ``meses`` (1 a 12). ``competencia`` define a tabela (mês do pagamento)."""
    salario = D(salario_base, "salário base")
    if salario <= 0:
        raise DadosInvalidos("O salário base deve ser maior que zero.")
    if not 1 <= int(meses) <= 12:
        raise DadosInvalidos("Meses de 13º devem estar entre 1 e 12.")
    rem = salario + nao_negativo(D(adicionais_mensais, "adicionais"), "adicionais") + nao_negativo(
        D(media_variaveis, "média de variáveis"), "média de variáveis"
    )
    total = q2(rem / 12 * int(meses))
    primeira = q2(total / 2) if adiantamento is None else nao_negativo(D(adiantamento, "adiantamento"), "adiantamento")
    inss = calcular_inss(total, competencia, caminho_tabelas).valor
    irrf = calcular_irrf_mensal(
        total, competencia, inss=inss, dependentes=dependentes, caminho_tabelas=caminho_tabelas
    ).valor
    segunda = total - primeira - inss - irrf
    return ResultadoDecimoTerceiro(
        meses=int(meses),
        total_bruto=total,
        primeira_parcela=primeira,
        inss=inss,
        irrf=irrf,
        segunda_parcela=segunda,
        explicacao=(
            f"13º de {meses}/12: ({rem} / 12) x {meses} = {total}.",
            f"1ª parcela (50%, sem descontos, até 30/11): {primeira}.",
            f"2ª parcela (até 20/12): {total} - {primeira} - INSS {inss} - IRRF {irrf} = {segunda}.",
        ),
    )
