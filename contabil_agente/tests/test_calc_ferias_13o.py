from datetime import date
from decimal import Decimal

import pytest

from contabil_agente.calc import DadosInvalidos, calcular_decimo_terceiro, calcular_ferias

D = Decimal
COMP = date(2026, 11, 1)


def test_ferias_de_30_dias():
    r = calcular_ferias("3000", COMP)
    # 3.000 / 30 x 30 = 3.000,00 + 1/3 (1.000,00) = 4.000,00 tributável
    assert r.valor_dias == D("3000.00") and r.terco == D("1000.00")
    # INSS(4.000) = 121,575 + 115,3656 + (4.000 - 2.902,84) x 12% (131,6592) = 368,5998 -> 368,60
    assert r.inss == D("368.60")
    # IRRF: legal base 3.631,40 -> x 15% - 394,16 = 150,55 ; simplificado base 3.392,80 -> 114,76 (menor)
    # R = 4.000 <= 5.000 -> redução máxima 312,89 limitada ao imposto (114,76) -> IRRF 0
    assert r.irrf == D("0.00")
    assert r.liquido == D("4000.00") - D("368.60")


def test_ferias_com_abono_pecuniario_isento():
    r = calcular_ferias("3000", COMP, dias_gozados=20, dias_vendidos=10)
    # gozados: 3.000 / 30 x 20 = 2.000,00 + 1/3 = 666,67 ; abono: 1.000,00 + 1/3 = 333,33 (isentos)
    assert r.valor_dias == D("2000.00") and r.terco == D("666.67")
    assert r.abono == D("1000.00") and r.terco_abono == D("333.33")
    # INSS só sobre 2.666,67: 121,575 + (2.666,67 - 1.621) x 9% = 94,1103 -> 215,6853 -> 215,69
    assert r.inss == D("215.69")
    assert r.bruto == D("4000.00")


def test_ferias_valida_dias():
    with pytest.raises(DadosInvalidos):
        calcular_ferias("3000", COMP, dias_gozados=25, dias_vendidos=10)
    with pytest.raises(DadosInvalidos):
        calcular_ferias("3000", COMP, dias_vendidos=11)
    with pytest.raises(DadosInvalidos):
        calcular_ferias("0", COMP)


def test_decimo_terceiro_integral():
    r = calcular_decimo_terceiro("3000", 12, date(2026, 12, 1))
    # total 3.000,00 ; 1ª parcela 1.500,00 ; INSS(3.000) = 248,60 ; IRRF = 0 (3.000 - 248,60 abaixo da faixa isenta)
    assert r.total_bruto == D("3000.00")
    assert r.primeira_parcela == D("1500.00")
    assert r.inss == D("248.60")
    assert r.irrf == D("0.00")
    assert r.segunda_parcela == D("1251.40")


def test_decimo_terceiro_proporcional_com_adiantamento_diferente():
    r = calcular_decimo_terceiro("3000", 8, date(2026, 12, 1), adiantamento="1000")
    # 3.000 / 12 x 8 = 2.000,00 ; INSS(2.000) = 121,575 + 379 x 9% (34,11) = 155,685 -> 155,69
    assert r.total_bruto == D("2000.00")
    assert r.inss == D("155.69")
    assert r.segunda_parcela == D("2000.00") - D("1000.00") - D("155.69")


def test_decimo_terceiro_alto_aplica_reducao_da_lei():
    r = calcular_decimo_terceiro("6000", 12, date(2026, 12, 1))
    # 13º = 6.000 ; INSS(6.000) = 641,51 ; igual ao IRRF mensal de 6.000 -> 385,10 (redução 179,75 também no 13º)
    assert r.inss == D("641.51")
    assert r.irrf == D("385.10")


def test_decimo_terceiro_valida_meses():
    with pytest.raises(DadosInvalidos):
        calcular_decimo_terceiro("3000", 13, date(2026, 12, 1))
