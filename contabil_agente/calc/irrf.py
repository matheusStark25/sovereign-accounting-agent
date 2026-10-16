"""IRRF mensal (rendimentos do trabalho) com a redução da Lei 15.270/2025.

Ordem de cálculo (Lei 9.250/1995, art. 3º-A, §1º, e Lei 11.482/2007, art. 1º):

1. ``rendimentos tributáveis`` (R) = total tributável do mês, antes de deduções.
2. Base de cálculo = R - deduções. O motor calcula duas bases e usa a mais
   vantajosa: (a) deduções legais (INSS, dependentes, pensão alimentícia) ou
   (b) desconto simplificado.
3. Imposto pela tabela progressiva mensal: base x alíquota - parcela a deduzir.
4. Redução (a partir de 01/2026): R até 5.000,00 -> até 312,89 (imposto zero);
   R de 5.000,01 a 7.350,00 -> 978,62 - 0,133145 x R; acima de 7.350,00 -> nenhuma.
   A redução nunca passa do imposto apurado no passo 3.
5. IRRF = imposto - redução, arredondado uma única vez (metade para cima).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from .money import ZERO, D, nao_negativo, q2
from .tables import TabelaIrrf, tabela_irrf


@dataclass(frozen=True)
class ResultadoIrrf:
    competencia: date
    rendimentos_tributaveis: Decimal
    opcao_deducao: str  # "legal" | "simplificado"
    base_calculo: Decimal
    imposto_tabela: Decimal
    reducao: Decimal
    valor: Decimal
    detalhe: dict
    norma: str
    verificacao: str


def imposto_pela_tabela(base: Decimal, tabela: TabelaIrrf) -> Decimal:
    """Imposto da tabela progressiva mensal para uma base já deduzida."""
    if base <= ZERO:
        return ZERO
    for faixa in tabela.faixas:
        if faixa.ate is None or base <= faixa.ate:
            return max(ZERO, base * faixa.aliquota - faixa.deducao)
    return ZERO  # inalcançável: a última faixa não tem limite


def reducao_do_imposto(rendimentos: Decimal, imposto: Decimal, tabela: TabelaIrrf) -> Decimal:
    """Redução do art. 3º-A da Lei 9.250/1995, limitada ao imposto apurado."""
    red = tabela.reducao
    if red is None or imposto <= ZERO:
        return ZERO
    if rendimentos <= red.ate:
        bruta = red.valor_maximo
    elif rendimentos <= red.parcial_ate:
        bruta = max(ZERO, red.constante - red.coeficiente * rendimentos)
    else:
        return ZERO
    return min(bruta, imposto)


def calcular_irrf_mensal(
    rendimentos_tributaveis,
    competencia: date,
    inss=0,
    dependentes: int = 0,
    pensao_alimenticia=0,
    outras_deducoes=0,
    caminho_tabelas: Optional[str] = None,
) -> ResultadoIrrf:
    """IRRF mensal sobre ``rendimentos_tributaveis`` (valor bruto tributável do mês)."""
    r = nao_negativo(D(rendimentos_tributaveis, "rendimentos tributáveis"), "rendimentos tributáveis")
    inss = nao_negativo(D(inss, "INSS"), "INSS")
    pensao = nao_negativo(D(pensao_alimenticia, "pensão alimentícia"), "pensão alimentícia")
    outras = nao_negativo(D(outras_deducoes, "outras deduções"), "outras deduções")
    if dependentes < 0 or int(dependentes) != dependentes:
        raise ValueError("dependentes deve ser um inteiro não negativo")
    tabela = tabela_irrf(competencia, caminho_tabelas)

    deducao_dependentes = tabela.deducao_dependente * int(dependentes)
    deducoes_legais = inss + deducao_dependentes + pensao + outras
    base_legal = max(ZERO, r - deducoes_legais)
    base_simplificada = max(ZERO, r - tabela.desconto_simplificado)

    imposto_legal = imposto_pela_tabela(base_legal, tabela)
    imposto_simplificado = imposto_pela_tabela(base_simplificada, tabela)

    if imposto_simplificado < imposto_legal:
        opcao, base, imposto = "simplificado", base_simplificada, imposto_simplificado
    else:
        opcao, base, imposto = "legal", base_legal, imposto_legal

    reducao = reducao_do_imposto(r, imposto, tabela)
    valor = q2(max(ZERO, imposto - reducao))

    return ResultadoIrrf(
        competencia=competencia,
        rendimentos_tributaveis=r,
        opcao_deducao=opcao,
        base_calculo=base,
        imposto_tabela=imposto,
        reducao=reducao,
        valor=valor,
        detalhe={
            "deducoes_legais": {
                "inss": inss,
                "dependentes": deducao_dependentes,
                "pensao_alimenticia": pensao,
                "outras": outras,
                "total": deducoes_legais,
            },
            "imposto_com_deducoes_legais": imposto_legal,
            "imposto_com_desconto_simplificado": imposto_simplificado,
            "desconto_simplificado": tabela.desconto_simplificado,
        },
        norma=tabela.norma,
        verificacao=tabela.verificacao,
    )
