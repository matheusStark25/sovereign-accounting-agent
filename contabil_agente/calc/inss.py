"""INSS do empregado: contribuição progressiva por faixas, limitada ao teto."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple

from .money import ZERO, D, nao_negativo, q2
from .tables import tabela_inss


@dataclass(frozen=True)
class ParteInss:
    de: Decimal
    ate: Decimal
    aliquota: Decimal
    base_na_faixa: Decimal
    valor: Decimal


@dataclass(frozen=True)
class ResultadoInss:
    competencia: date
    base: Decimal
    base_limitada_ao_teto: Decimal
    valor: Decimal
    partes: Tuple[ParteInss, ...]
    norma: str
    verificacao: str


def calcular_inss(base, competencia: date, caminho_tabelas: Optional[str] = None) -> ResultadoInss:
    """Calcula o INSS do empregado sobre ``base`` (salário de contribuição).

    Método progressivo: cada alíquota incide só sobre a parte da base que cai na
    sua faixa; o total é arredondado uma única vez (metade para cima).
    """
    base = nao_negativo(D(base, "base do INSS"), "base do INSS")
    tabela = tabela_inss(competencia, caminho_tabelas)
    limitada = min(base, tabela.teto)

    partes = []
    total = ZERO
    inferior = ZERO
    for faixa in tabela.faixas:
        if limitada > inferior:
            na_faixa = min(limitada, faixa.ate) - inferior
            valor = na_faixa * faixa.aliquota
            partes.append(ParteInss(inferior, faixa.ate, faixa.aliquota, na_faixa, valor))
            total += valor
        inferior = faixa.ate

    return ResultadoInss(
        competencia=competencia,
        base=base,
        base_limitada_ao_teto=limitada,
        valor=q2(total),
        partes=tuple(partes),
        norma=tabela.norma,
        verificacao=tabela.verificacao,
    )
