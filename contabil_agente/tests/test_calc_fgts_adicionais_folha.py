"""FGTS, adicionais e folha: valores conferidos à mão (competência 09/2026)."""

from datetime import date
from decimal import Decimal

import pytest

from contabil_agente.calc import (
    CompetenciaSemTabela,
    DadosInvalidos,
    calcular_fgts_mensal,
    calcular_folha,
    calcular_multa_fgts,
)
from contabil_agente.calc import adicionais
from contabil_agente.calc.servico import calcular

COMP = date(2026, 9, 1)


def test_fgts_empregado_8_por_cento():
    assert calcular_fgts_mensal("3000").valor == Decimal("240.00")


def test_fgts_aprendiz_2_por_cento_e_domestico_11_2():
    assert calcular_fgts_mensal(1000, "aprendiz").valor == Decimal("20.00")
    assert calcular_fgts_mensal(1000, "domestico").valor == Decimal("112.00")


def test_fgts_categoria_invalida():
    with pytest.raises(DadosInvalidos):
        calcular_fgts_mensal(1000, "marciano")


def test_multa_fgts_sobre_saldo_mais_deposito_rescisorio():
    assert calcular_multa_fgts(12000, "sem_justa_causa", 632) == Decimal("5052.80")
    assert calcular_multa_fgts(12000, "acordo", 632) == Decimal("2526.40")
    assert calcular_multa_fgts(12000, "justa_causa", 632) == Decimal("0.00")


def test_periculosidade_30_por_cento():
    assert adicionais.periculosidade(3000) == Decimal("900.00")


def test_insalubridade_usa_o_salario_minimo_da_competencia():
    assert adicionais.insalubridade("medio", COMP) == Decimal("324.20")  # 1621 x 20%
    assert adicionais.insalubridade("maximo", COMP) == Decimal("648.40")
    with pytest.raises(CompetenciaSemTabela):
        adicionais.insalubridade("medio", date(2031, 1, 1))
    with pytest.raises(DadosInvalidos):
        adicionais.insalubridade("enorme", COMP)


def test_horas_extras_com_dsr():
    r = adicionais.horas_extras(3300, 10, 50, dias_uteis=25, domingos_feriados=5)
    assert r["valor_hora"] == Decimal("15")  # 3300 / 220
    assert r["valor"] == Decimal("225.00")  # 15 x 1,5 x 10
    assert r["dsr"] == Decimal("45.00")  # 225 / 25 x 5
    assert r["total"] == Decimal("270.00")


def test_hora_extra_abaixo_de_50_por_cento_e_recusada():
    with pytest.raises(DadosInvalidos):
        adicionais.horas_extras(3300, 10, 30)


def test_adicional_noturno_20_por_cento():
    assert adicionais.adicional_noturno(2200, 40) == Decimal("80.00")  # 10 x 40 x 20%


def test_folha_salario_6000():
    r = calcular_folha(6000, COMP)
    assert r.descontos["inss"] == Decimal("641.51")
    # base 6000 - 641,51 = 5358,49; 27,5% - 908,73 = 564,85; reducao 978,62 - 0,133145 x 6000 = 179,75
    assert r.descontos["irrf"] == Decimal("385.10")
    assert r.liquido == Decimal("4973.39")
    assert r.fgts == Decimal("480.00")


def test_folha_baixa_renda_fica_isenta_e_desconta_vt_limitado_a_6_por_cento():
    r = calcular_folha(3000, COMP, custo_vale_transporte=300)
    assert r.descontos["irrf"] == Decimal("0.00")
    assert r.descontos["vale_transporte"] == Decimal("180.00")
    assert r.liquido == Decimal("2571.40")


def test_folha_vt_menor_que_6_por_cento_desconta_so_o_custo():
    r = calcular_folha(3000, COMP, custo_vale_transporte=100)
    assert r.descontos["vale_transporte"] == Decimal("100.00")


def test_folha_com_adicionais_aumenta_base_do_inss_e_do_fgts():
    r = calcular_folha(3000, COMP, adicionais_mensais=900)
    assert r.total_proventos == Decimal("3900")
    assert r.fgts == Decimal("312.00")


def test_servico_expoe_fgts_e_folha():
    ok = calcular("fgts", {"salario": 3000}, hoje=COMP)
    assert ok["status"] == "ok" and ok["resultado"]["fgts"] == 240.0
    folha = calcular("folha", {"salario": 6000, "competencia": "2026-09-01"})
    assert folha["status"] == "ok" and folha["resultado"]["total_liquido"] == 4973.39
    assert calcular("folha", {})["status"] == "faltam_dados"
