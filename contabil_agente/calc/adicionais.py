"""Adicionais da remuneração: periculosidade, insalubridade, horas extras com DSR e adicional noturno.

* Periculosidade: 30% do salário base, sem gratificações e prêmios (CLT 193, §1º).
* Insalubridade: 10%, 20% ou 40% do salário mínimo (CLT 192); o mínimo vem da tabela da competência.
* Horas extras: valor da hora × (1 + percentual); percentual mínimo de 50% (CF 7º, XVI).
  O DSR sobre horas extras (Lei 605/1949) é opcional: informe dias úteis e domingos/feriados do mês.
* Adicional noturno: 20% sobre a hora (CLT 73). A hora noturna reduzida (52min30s) não é calculada.

Os resultados integram INSS, IRRF, FGTS, férias e 13º: some-os à remuneração antes de calcular.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from .errors import DadosInvalidos
from .money import ZERO, D, nao_negativo, q2
from .tables import tabela_inss

PERICULOSIDADE = Decimal("0.30")
INSALUBRIDADE = {"minimo": Decimal("0.10"), "medio": Decimal("0.20"), "maximo": Decimal("0.40")}
ADICIONAL_NOTURNO = Decimal("0.20")
DIVISOR_PADRAO = Decimal("220")  # jornada de 44h semanais


def periculosidade(salario_base) -> Decimal:
    salario = nao_negativo(D(salario_base, "salário base"), "salário base")
    return q2(salario * PERICULOSIDADE)


def insalubridade(grau: str, competencia: date, caminho_tabelas: Optional[str] = None) -> Decimal:
    percentual = INSALUBRIDADE.get(str(grau).strip().lower())
    if percentual is None:
        raise DadosInvalidos(f"Grau de insalubridade inválido: {grau!r}. Use: minimo, medio ou maximo.")
    minimo = tabela_inss(competencia, caminho_tabelas).salario_minimo
    return q2(minimo * percentual)


def valor_hora(salario_mensal, divisor=DIVISOR_PADRAO) -> Decimal:
    salario = nao_negativo(D(salario_mensal, "salário"), "salário")
    div = D(divisor, "divisor")
    if div <= 0:
        raise DadosInvalidos("O divisor da jornada deve ser maior que zero.")
    return salario / div


def horas_extras(
    salario_mensal,
    horas,
    percentual=50,
    divisor=DIVISOR_PADRAO,
    dias_uteis: int = 0,
    domingos_feriados: int = 0,
) -> dict:
    """Valor das horas extras e, se informados os dias do mês, o DSR correspondente."""
    qtd = nao_negativo(D(horas, "horas extras"), "horas extras")
    perc = D(percentual, "percentual")
    if perc < 50:
        raise DadosInvalidos("O adicional de hora extra não pode ser menor que 50% (CF art. 7º, XVI).")
    hora = valor_hora(salario_mensal, divisor)
    valor = q2(hora * (1 + perc / 100) * qtd)
    dsr = ZERO
    if dias_uteis > 0 and domingos_feriados > 0:
        dsr = q2(valor / dias_uteis * domingos_feriados)
    return {"valor_hora": hora, "valor": valor, "dsr": dsr, "total": valor + dsr}


def adicional_noturno(salario_mensal, horas_noturnas, divisor=DIVISOR_PADRAO) -> Decimal:
    """Só o adicional de 20% sobre as horas noturnas informadas (a hora reduzida não é calculada aqui)."""
    horas = nao_negativo(D(horas_noturnas, "horas noturnas"), "horas noturnas")
    return q2(valor_hora(salario_mensal, divisor) * horas * ADICIONAL_NOTURNO)
