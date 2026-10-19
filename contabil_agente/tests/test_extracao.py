from decimal import Decimal

import pytest

from contabil_agente.intelligence import extracao as ex

D = Decimal


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("3.000,50", "3000.50"),
        ("3000", "3000"),
        ("3.000", "3000"),
        ("R$ 12.345,67", "12345.67"),
        ("3k", "3000"),
        ("3,5 mil", "3500"),
        ("2 mil", "2000"),
    ],
)
def test_parse_valor_br(texto, esperado):
    assert ex.parse_valor_br(texto) == D(esperado)


def test_rescisao_completa_em_uma_frase():
    d = ex.extrair_dados(
        "Quero calcular a rescisão sem justa causa do João, salário de R$ 3.000,00, admitido em 10/03/2023, "
        "demitido em 15/09/2026, aviso indenizado, saldo do FGTS R$ 12.000,00, sem dependentes"
    )
    assert d["salario"] == D("3000.00")
    assert d["tipo_rescisao"] == "sem_justa_causa"
    assert d["data_admissao"] == "2023-03-10" and d["data_demissao"] == "2026-09-15"
    assert d["aviso_previo"] == "indenizado"
    assert d["saldo_fgts"] == D("12000.00")
    assert d["dependentes"] == 0


def test_saldo_do_fgts_nao_vira_salario():
    d = ex.extrair_dados("saldo do FGTS de R$ 12.000 e salário 3000")
    assert d["saldo_fgts"] == D("12000")
    assert d["salario"] == D("3000")


def test_duas_datas_sem_contexto_a_mais_antiga_e_admissao():
    d = ex.extrair_dados("trabalhou de 01/02/2020 até 30/06/2026")
    assert d["data_admissao"] == "2020-02-01" and d["data_demissao"] == "2026-06-30"


def test_uma_data_sem_contexto_fica_a_parte():
    d = ex.extrair_dados("foi em 15/09/2026")
    assert d["datas_sem_contexto"] == ["2026-09-15"]
    assert "data_admissao" not in d and "data_demissao" not in d


def test_ano_com_dois_digitos():
    assert ex.extrair_datas("admitido em 10/03/23")["data_admissao"] == "2023-03-10"


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("demitido sem justa causa", "sem_justa_causa"),
        ("foi demitido por justa causa", "justa_causa"),
        ("pediu demissão", "pedido_demissao"),
        ("pedido de demissão", "pedido_demissao"),
        ("rescisão por acordo", "acordo"),
        ("só uma conversa", None),
    ],
)
def test_tipo_de_rescisao(texto, esperado):
    assert ex.extrair_dados(texto).get("tipo_rescisao") == esperado


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("aviso indenizado", "indenizado"),
        ("aviso prévio trabalhado", "trabalhado"),
        ("não cumpriu o aviso", "nao_cumprido"),
        ("sem informação", None),
    ],
)
def test_aviso(texto, esperado):
    assert ex.extrair_dados(texto).get("aviso_previo") == esperado


def test_ferias_com_abono_e_dependentes():
    d = ex.extrair_dados("férias de 20 dias, vender 10 dias, salário 3000 e 2 dependentes")
    assert d["dias_ferias"] == 20 and d["dias_vendidos"] == 10 and d["dependentes"] == 2


def test_meses_do_13o():
    assert ex.extrair_dados("13º de 8 meses salário 3000")["meses"] == 8


def test_ferias_vencidas():
    assert ex.extrair_dados("tem férias vencidas")["periodos_ferias_vencidas"] == 1
    assert ex.extrair_dados("sem férias vencidas")["periodos_ferias_vencidas"] == 0
    assert ex.extrair_dados("2 períodos de férias vencidas")["periodos_ferias_vencidas"] == 2


def test_nao_inventa_nada():
    assert ex.extrair_dados("oi, tudo bem?") == {}


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("calcule a rescisão do João", "rescisao"),
        ("ele foi demitido ontem", "rescisao"),
        ("quanto fica o 13º?", "decimo_terceiro"),
        ("décimo terceiro de 8 meses", "decimo_terceiro"),
        ("minhas férias de 30 dias", "ferias"),
        ("calcular INSS de 5000", "inss"),
        ("quanto de imposto de renda?", "irrf"),
        ("bom dia", None),
    ],
)
def test_detectar_tipo_calculo(texto, esperado):
    assert ex.detectar_tipo_calculo(texto) == esperado


@pytest.mark.parametrize("frase,campo,valor", [
    ("funcionário que ganha 3 mil", "salario", "3000"),
    ("salário de 4,5 mil", "salario", "4500"),
    ("INSS de 5 mil", "salario", "5000"),
    ("salário 3k", "salario", "3000"),
    ("quanto custa um pró-labore de 8 mil?", "prolabore", "8000"),
    ("pró-labore de R$ 12.500,00", "prolabore", "12500"),
])
def test_valores_escritos_por_extenso_em_mil_ou_k(frase, campo, valor):
    # antes, "3 mil" virava R$ 3: o número casava antes da palavra "mil"
    assert ex.extrair_dados(frase)[campo] == Decimal(valor)


@pytest.mark.parametrize("frase", [
    "Tem algum problema no último holerite que eu mandei?",
    "Qual o prazo para pagar a rescisão?",
    "quanto tempo tenho para pagar a rescisão?",
    "o que é férias vencidas?",
    "confere o DAS que eu mandei",
    "posso parcelar o DARF?",
    "tem direito a férias quem tem 6 meses?",
])
def test_pergunta_sobre_documento_ou_regra_nao_vira_calculo(frase):
    # vão para a assistente, que consulta os documentos e explica a regra; antes abriam um formulário de cálculo
    assert ex.detectar_tipo_calculo(frase) is None


@pytest.mark.parametrize("frase,tipo", [
    ("calcular o holerite de quem ganha 3000", "folha"),
    ("o holerite de 3000 com 2 dependentes", "folha"),
    ("qual o desconto do INSS de quem ganha 3 mil?", "inss"),
    ("calcular DARF de 1000 vencido em 10/08/2026", "darf"),
])
def test_pedido_de_conta_continua_indo_para_o_motor(frase, tipo):
    assert ex.detectar_tipo_calculo(frase) == tipo


def test_mes_e_ano_viram_competencia_e_nao_salario():
    # antes, "INSS em setembro de 2026" virava salário de R$ 2.026
    d = ex.extrair_dados("calcular INSS de 4500 em setembro de 2026")
    assert d["competencia"] == "01/09/2026" and d["salario"] == Decimal("4500")
    assert ex.extrair_dados("inss de 3 mil competência 09/2026")["competencia"] == "01/09/2026"
    assert "competencia" not in ex.extrair_dados("admitido em 10/03/2023, demitido em 15/09/2026")  # data completa não é competência
    assert ex.detectar_tipo_calculo("Quais são as faixas do INSS em setembro de 2026 e qual a norma?") is None  # vai para tabela_vigente


def test_darf_vencido_em_conta_como_vencimento():
    d = ex.extrair_dados("DARF vencido em 20/08/2026 pago em 10/10/2026")
    assert d["vencimento"] == "2026-08-20" and d["pagamento"] == "2026-10-10"
