from datetime import date

import pytest

from contabil_agente.calc import datas


def test_somar_meses_ajusta_fim_de_mes():
    assert datas.somar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert datas.somar_meses(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert datas.somar_meses(date(2026, 11, 15), 3) == date(2027, 2, 15)


@pytest.mark.parametrize(
    "admissao, demissao, esperado",
    [
        (date(2023, 3, 10), date(2026, 9, 15), 3),  # 3 anos e 6 meses
        (date(2023, 3, 10), date(2026, 3, 10), 3),  # no aniversário já completou
        (date(2023, 3, 10), date(2026, 3, 9), 2),  # um dia antes ainda não completou
        (date(2026, 1, 1), date(2026, 6, 1), 0),
    ],
)
def test_anos_completos(admissao, demissao, esperado):
    assert datas.anos_completos(admissao, demissao) == esperado


def test_fracao_de_15_dias_conta_como_mes():
    # 10/03 a 24/10: 7 meses completos (10/03-09/10) + 15 dias (10/10 a 24/10, ambos inclusive)
    assert datas.meses_e_dias(date(2026, 3, 10), date(2026, 10, 24)) == (7, 15)
    assert datas.meses_com_fracao(date(2026, 3, 10), date(2026, 10, 24)) == 8
    # um dia a menos: 14 dias -> não conta
    assert datas.meses_e_dias(date(2026, 3, 10), date(2026, 10, 23)) == (7, 14)
    assert datas.meses_com_fracao(date(2026, 3, 10), date(2026, 10, 23)) == 7


def test_periodo_aquisitivo_comeca_no_ultimo_aniversario():
    assert datas.inicio_periodo_aquisitivo(date(2023, 3, 10), date(2026, 10, 24)) == date(2026, 3, 10)
    # com menos de 1 ano, o período começa na admissão
    assert datas.inicio_periodo_aquisitivo(date(2026, 3, 10), date(2026, 10, 24)) == date(2026, 3, 10)


def test_13o_conta_meses_com_15_dias_ou_mais():
    # admitido desde 2023, dispensado em 24/10/2026: janeiro a outubro = 10 meses
    assert datas.meses_de_13o_no_ano(date(2023, 3, 10), date(2026, 10, 24), 2026) == 10
    # dispensado em 14/10: outubro tem só 14 dias -> 9 meses
    assert datas.meses_de_13o_no_ano(date(2023, 3, 10), date(2026, 10, 14), 2026) == 9
    # admitido em 20/03: março teve 12 dias (20 a 31) -> não conta; abril a dezembro = 9 meses
    assert datas.meses_de_13o_no_ano(date(2026, 3, 20), date(2026, 12, 31), 2026) == 9
    # admitido em 17/03: março teve 15 dias (17 a 31) -> conta; março a dezembro = 10 meses
    assert datas.meses_de_13o_no_ano(date(2026, 3, 17), date(2026, 12, 31), 2026) == 10
