"""Testes do INSS e do IRRF com valores calculados à mão.

Cada valor esperado tem a conta escrita ao lado, para que um contador possa
conferir sem rodar o código.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from contabil_agente.calc import CompetenciaSemTabela, calcular_inss, calcular_irrf_mensal
from contabil_agente.calc import tables

D = Decimal
C2026 = date(2026, 9, 1)
C2025 = date(2025, 6, 1)


# ----------------------------------------------------------------- tabelas
def test_arquivo_de_tabelas_e_consistente():
    with open(tables.ARQUIVO_PADRAO, encoding="utf-8") as fh:
        assert tables.validar(json.load(fh)) == []


def test_validacao_pega_parcela_a_deduzir_errada():
    with open(tables.ARQUIVO_PADRAO, encoding="utf-8") as fh:
        bruto = json.load(fh)
    bruto["inss_empregado"][1]["parcelas_a_deduzir_conferencia"][2] = "999.99"
    assert any("parcela a deduzir" in p for p in tables.validar(bruto))


def test_validacao_pega_vigencias_sobrepostas():
    with open(tables.ARQUIVO_PADRAO, encoding="utf-8") as fh:
        bruto = json.load(fh)
    bruto["irrf_mensal"][0]["vigencia_fim"] = "2026-03-31"
    assert any("sobrep" in p for p in tables.validar(bruto))


def test_validacao_pega_reducao_que_nao_zera():
    with open(tables.ARQUIVO_PADRAO, encoding="utf-8") as fh:
        bruto = json.load(fh)
    bruto["irrf_mensal"][1]["reducao"]["constante"] = "900.00"
    assert any("redução" in p for p in tables.validar(bruto))


def test_competencia_sem_tabela_gera_erro_e_nao_estimativa():
    with pytest.raises(CompetenciaSemTabela):
        calcular_inss(3000, date(2024, 12, 1))
    with pytest.raises(CompetenciaSemTabela):
        calcular_inss(3000, date(2027, 1, 1))  # a tabela do INSS é anual
    with pytest.raises(CompetenciaSemTabela):
        calcular_irrf_mensal(3000, date(2025, 4, 1))  # tabela anterior a 05/2025 não carregada


# -------------------------------------------------------------------- INSS
@pytest.mark.parametrize(
    "base, esperado",
    [
        # 1.621,00 x 7,5% = 121,575 -> 121,58 (metade para cima)
        ("1621.00", "121.58"),
        # 121,575 + (2.902,84-1.621,00) x 9% = 115,3656 + (3.000-2.902,84) x 12% = 11,6592 -> 248,5998
        ("3000.00", "248.60"),
        # 121,575 + 115,3656 + (4.354,27-2.902,84) x 12% = 174,1716 + (5.000-4.354,27) x 14% = 90,4022 -> 501,5144
        ("5000.00", "501.51"),
        # teto: 121,575 + 115,3656 + 174,1716 + (8.475,55-4.354,27) x 14% = 576,9792 -> 988,0914
        ("8475.55", "988.09"),
        ("20000.00", "988.09"),  # acima do teto a contribuição não cresce
        ("0", "0.00"),
    ],
)
def test_inss_2026(base, esperado):
    assert calcular_inss(base, C2026).valor == D(esperado)


def test_inss_2026_confere_pelo_metodo_da_parcela_a_deduzir():
    """Método alternativo publicado na portaria: base x alíquota - parcela a deduzir."""
    casos = [
        (D("1500"), D("0.075"), D("0")),
        (D("2500"), D("0.09"), D("24.32")),
        (D("4000"), D("0.12"), D("111.40")),
        (D("7000"), D("0.14"), D("198.49")),
    ]
    for base, aliquota, parcela in casos:
        por_parcela = (base * aliquota - parcela).quantize(D("0.01"))
        assert abs(calcular_inss(base, C2026).valor - por_parcela) <= D("0.01"), base


def test_inss_2025():
    # 1.518 x 7,5% = 113,85 ; (2.793,88-1.518) x 9% = 114,8292 ; (3.000-2.793,88) x 12% = 24,7344 -> 253,4136
    assert calcular_inss("3000", C2025).valor == D("253.41")


def test_inss_recusa_valor_negativo():
    from contabil_agente.calc import DadosInvalidos

    with pytest.raises(DadosInvalidos):
        calcular_inss("-1", C2026)


# -------------------------------------------------------------------- IRRF
def test_irrf_2026_salario_de_5000_e_isento_pela_lei_15270():
    # INSS = 501,51. Desconto simplificado: base 5.000-607,20 = 4.392,80
    # imposto = 4.392,80 x 22,5% - 675,49 = 988,38 - 675,49 = 312,89 ; redução máxima 312,89 -> IRRF 0
    r = calcular_irrf_mensal("5000", C2026, inss="501.51")
    assert r.opcao_deducao == "simplificado"
    assert r.imposto_tabela == D("312.89")
    assert r.reducao == D("312.89")
    assert r.valor == D("0.00")


def test_irrf_2026_salario_de_6000_com_reducao_parcial():
    # INSS(6.000) = 641,51. Deduções legais: base 5.358,49 -> 5.358,49 x 27,5% - 908,73 = 564,85475
    # (simplificado daria 574,29: perde). Redução: 978,62 - 0,133145 x 6.000 = 978,62 - 798,87 = 179,75
    # IRRF = 564,85475 - 179,75 = 385,10475 -> 385,10
    inss = calcular_inss("6000", C2026).valor
    assert inss == D("641.51")
    r = calcular_irrf_mensal("6000", C2026, inss=inss)
    assert r.opcao_deducao == "legal"
    assert r.base_calculo == D("5358.49")
    assert r.reducao == D("179.75")
    assert r.valor == D("385.10")


def test_irrf_2026_com_dois_dependentes():
    # deduções: 641,51 + 2 x 189,59 = 1.020,69 -> base 4.979,31 -> x 27,5% = 1.369,31025 - 908,73 = 460,58025
    # redução 179,75 -> 280,83025 -> 280,83
    r = calcular_irrf_mensal("6000", C2026, inss="641.51", dependentes=2)
    assert r.valor == D("280.83")


def test_irrf_2026_acima_de_7350_sem_reducao():
    # INSS(8.000) = 921,51 -> base 7.078,49 x 27,5% = 1.946,58475 - 908,73 = 1.037,85475 -> 1.037,85
    inss = calcular_inss("8000", C2026).valor
    assert inss == D("921.51")
    r = calcular_irrf_mensal("8000", C2026, inss=inss)
    assert r.reducao == D("0")
    assert r.valor == D("1037.85")


def test_irrf_2026_em_7350_a_reducao_ja_e_menor_que_um_centavo():
    r = calcular_irrf_mensal("7350", C2026, inss=calcular_inss("7350", C2026).valor)
    # 978,62 - 0,133145 x 7.350 = 978,62 - 978,61575 = 0,00425: a lei manda zerar "a partir de" 7.350
    assert r.reducao < D("0.01")
    assert r.valor == r.imposto_tabela.quantize(D("0.01"))  # na prática, sem redução
    # um centavo acima de 7.350 a redução é exatamente zero
    acima = calcular_irrf_mensal("7350.01", C2026, inss=calcular_inss("7350.01", C2026).valor)
    assert acima.reducao == D("0")


def test_irrf_reducao_nunca_passa_do_imposto():
    # rendimento baixo: imposto 0 -> redução 0 (não gera crédito)
    r = calcular_irrf_mensal("2000", C2026, inss="150")
    assert r.imposto_tabela == D("0")
    assert r.reducao == D("0")
    assert r.valor == D("0.00")


def test_irrf_2025_sem_reducao_da_lei_15270():
    # INSS(5.000, 2025) = 509,60. Simplificado: base 4.392,80 -> 312,89 ; legal: base 4.490,40 -> 334,85.
    # Em 2025 não há redução: IRRF = menor imposto = 312,89
    inss = calcular_inss("5000", C2025).valor
    assert inss == D("509.60")
    r = calcular_irrf_mensal("5000", C2025, inss=inss)
    assert r.reducao == D("0")
    assert r.valor == D("312.89")


def test_irrf_tabela_progressiva_e_continua_nos_limites():
    """Imposto não pode 'pular' ao passar de uma faixa para a outra."""
    from contabil_agente.calc.irrf import imposto_pela_tabela

    tabela = tables.tabela_irrf(C2026)
    for limite in (D("2826.65"), D("3751.05"), D("4664.68")):
        antes = imposto_pela_tabela(limite, tabela)
        depois = imposto_pela_tabela(limite + D("0.01"), tabela)
        assert abs(depois - antes) < D("0.05"), limite
