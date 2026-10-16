"""Regras de contagem de tempo usadas em rescisão, férias e 13º salário."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Tuple


def somar_meses(data: date, meses: int) -> date:
    """Soma meses mantendo o dia, ou o último dia do mês quando ele não existir."""
    indice = data.year * 12 + (data.month - 1) + meses
    ano, mes = divmod(indice, 12)
    mes += 1
    ultimo = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(data.day, ultimo))


def anos_completos(inicio: date, fim: date) -> int:
    """Anos inteiros de serviço entre ``inicio`` e ``fim`` (para o aviso prévio proporcional)."""
    anos = fim.year - inicio.year
    if somar_meses(inicio, 12 * anos) > fim:
        anos -= 1
    return max(0, anos)


def meses_e_dias(inicio: date, fim_inclusive: date) -> Tuple[int, int]:
    """Meses completos e dias restantes, contando o último dia como trabalhado.

    O fim é inclusivo: o dia da dispensa (ou do último dia do aviso) é dia de serviço.
    """
    fim_exclusivo = fim_inclusive + timedelta(days=1)
    meses = (fim_exclusivo.year - inicio.year) * 12 + (fim_exclusivo.month - inicio.month)
    if somar_meses(inicio, meses) > fim_exclusivo:
        meses -= 1
    meses = max(0, meses)
    dias = (fim_exclusivo - somar_meses(inicio, meses)).days
    return meses, dias


def meses_com_fracao(inicio: date, fim_inclusive: date) -> int:
    """Meses completos + 1 se a fração restante tiver 15 dias ou mais (CLT art. 146, p.u.)."""
    meses, dias = meses_e_dias(inicio, fim_inclusive)
    return meses + (1 if dias >= 15 else 0)


def inicio_periodo_aquisitivo(admissao: date, referencia: date) -> date:
    """Início do período aquisitivo de férias em curso na data ``referencia``."""
    return somar_meses(admissao, 12 * anos_completos(admissao, referencia))


def meses_de_13o_no_ano(admissao: date, fim: date, ano: int) -> int:
    """Meses do ano ``ano`` que contam para o 13º proporcional.

    Lei 4.090/1962, art. 1º, §1º: fração igual ou superior a 15 dias de trabalho
    no mês conta como mês integral. Conta mês a mês, de janeiro a dezembro.
    """
    total = 0
    for mes in range(1, 13):
        primeiro = date(ano, mes, 1)
        ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
        inicio_trab = max(primeiro, admissao)
        fim_trab = min(ultimo, fim)
        if fim_trab >= inicio_trab and (fim_trab - inicio_trab).days + 1 >= 15:
            total += 1
    return total
