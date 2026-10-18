"""Pró-labore, GPS, DAS do MEI e DARF em atraso: valores conferidos à mão, vencimentos, chat, PDF e API do motor."""

from datetime import date

import pytest

from contabil_agente.calc import servico
from contabil_agente.calc.encargos import (
    FaltamDados,
    _pascoa,
    calcular_darf,
    calcular_das_mei,
    calcular_gps,
    calcular_prolabore,
    feriados_nacionais,
)
from contabil_agente.calc.errors import DadosInvalidos
from contabil_agente.calc.irrf import calcular_irrf_mensal
from contabil_agente.documentos.pdf import gerar_pdf_calculo
from contabil_agente.intelligence.dialogo_calculo import DialogoCalculo

COMP = date(2026, 10, 1)  # salário mínimo 1.621,00 e teto do INSS 8.475,55 (calc/data/tabelas.yaml)


# ------------------------------------------------------------------------------------------------- pró-labore
def test_prolabore_lucro_presumido_inss_11_irrf_e_patronal_20():
    r = calcular_prolabore(5000, COMP, regime="presumido")
    assert r["inss_socio"] == 550.00 and r["inss_patronal"] == 1000.00 and r["custo_total_empresa"] == 6000.00
    irrf = calcular_irrf_mensal(5000, COMP, inss=550).valor  # o mesmo motor de IRRF do resto do sistema
    assert r["irrf"] == float(irrf) and r["liquido"] == round(5000 - 550 - float(irrf), 2)


def test_prolabore_no_simples_nao_tem_patronal_a_parte():
    r = calcular_prolabore(5000, COMP, regime="simples")
    assert r["inss_patronal"] == 0 and r["custo_total_empresa"] == 5000.00 and any("Simples" in a for a in r["avisos"])
    assert calcular_prolabore(5000, COMP, regime="simples_anexo_iv")["inss_patronal"] == 1000.00


def test_prolabore_abaixo_do_minimo_e_acima_do_teto():
    abaixo = calcular_prolabore(1000, COMP)
    assert abaixo["base_inss_socio"] == 1621.00 and abaixo["inss_socio"] == 178.31 and any("abaixo do salário mínimo" in a for a in abaixo["avisos"])
    acima = calcular_prolabore(10000, COMP, regime="presumido")
    assert acima["base_inss_socio"] == 8475.55 and acima["inss_socio"] == 932.31 and acima["inss_patronal"] == 2000.00  # patronal sem teto


def test_prolabore_recusa_regime_invalido_e_valor_nao_positivo():
    with pytest.raises(DadosInvalidos):
        calcular_prolabore(5000, COMP, regime="inventado")
    with pytest.raises(DadosInvalidos):
        calcular_prolabore(0, COMP)


# --------------------------------------------------------------------------------------------------------- GPS
@pytest.mark.parametrize("tipo,base,base_usada,valor", [
    ("contribuinte_individual", 4000, 4000.00, 800.00),
    ("contribuinte_individual", 500, 1621.00, 324.20),  # base mínima: 1 salário mínimo
    ("contribuinte_individual", 20000, 8475.55, 1695.11),  # base máxima: o teto
    ("facultativo", 3000, 3000.00, 600.00),
    ("plano_simplificado", None, 1621.00, 178.31),  # 11% do salário mínimo
    ("baixa_renda", None, 1621.00, 81.05),  # 5% do salário mínimo
])
def test_gps_aliquotas_e_limites(tipo, base, base_usada, valor):
    r = calcular_gps(tipo, COMP, base=base)
    assert r["base"] == base_usada and r["valor"] == valor


def test_gps_vencimento_dia_15_vai_para_o_proximo_dia_util():
    # 15/11/2026 é domingo e feriado nacional: vence na segunda, 16/11
    assert calcular_gps("baixa_renda", COMP)["vencimento"] == "2026-11-16"
    # 15/07/2026 é quarta-feira
    assert calcular_gps("baixa_renda", date(2026, 6, 1))["vencimento"] == "2026-07-15"


def test_gps_sem_base_pergunta_em_vez_de_estimar():
    with pytest.raises(FaltamDados) as e:
        calcular_gps("contribuinte_individual", COMP)
    assert e.value.faltando == ["base"]
    with pytest.raises(DadosInvalidos):
        calcular_gps("astrologo", COMP)


# --------------------------------------------------------------------------------------------------- DAS do MEI
@pytest.mark.parametrize("atividade,valor,icms,iss", [
    ("comercio", 82.05, 1.00, 0.00),  # 5% de 1.621,00 = 81,05 + ICMS 1,00
    ("industria", 82.05, 1.00, 0.00),
    ("servicos", 86.05, 0.00, 5.00),  # 81,05 + ISS 5,00
    ("comercio_e_servicos", 87.05, 1.00, 5.00),
    ("caminhoneiro", 195.52, 1.00, 0.00),  # 12% de 1.621,00 = 194,52 + ICMS 1,00
])
def test_das_mei_valores_de_2026(atividade, valor, icms, iss):
    r = calcular_das_mei(atividade, COMP)
    assert r["valor"] == valor and r["icms"] == icms and r["iss"] == iss


def test_das_mei_vencimento_considera_feriado_nacional():
    # 20/11/2026 é sexta e feriado (Consciência Negra): vence na segunda, 23/11
    assert calcular_das_mei("servicos", COMP)["vencimento"] == "2026-11-23"
    assert calcular_das_mei("servicos", date(2026, 7, 1))["vencimento"] == "2026-08-20"
    with pytest.raises(DadosInvalidos):
        calcular_das_mei("mineracao", COMP)


# -------------------------------------------------------------------------------------------------------- DARF
def test_darf_no_prazo_ou_adiantado_nao_tem_acrescimo():
    r = calcular_darf(1000, "20/08/2026", "20/08/2026")
    assert r["multa"] == 0 and r["juros"] == 0 and r["total"] == 1000.00 and r["dias_de_atraso"] == 0
    assert calcular_darf(1000, "20/08/2026", "10/08/2026")["total"] == 1000.00


def test_darf_atraso_no_mesmo_mes_so_tem_multa():
    r = calcular_darf(1000, "10/08/2026", "15/08/2026")  # 5 dias x 0,33% = 1,65%
    assert r["multa"] == 16.50 and r["juros"] == 0 and r["total"] == 1016.50


def test_darf_mes_seguinte_juros_de_1_por_cento_sem_pedir_selic():
    r = calcular_darf(1000, "28/08/2026", "10/09/2026")  # 13 dias x 0,33% = 4,29%; sem mês cheio no meio
    assert r["multa"] == 42.90 and r["juros"] == 10.00 and r["total"] == 1052.90


def test_darf_com_mes_cheio_no_meio_pergunta_a_selic_e_depois_calcula():
    with pytest.raises(FaltamDados) as e:
        calcular_darf(1000, "20/08/2026", "15/10/2026")
    assert e.value.faltando == ["selic_acumulada"]
    r = calcular_darf(1000, "20/08/2026", "15/10/2026", selic_acumulada=0.9)  # 56 dias = 18,48%; SELIC 0,9% + 1%
    assert r["multa"] == 184.80 and r["juros"] == 19.00 and r["total"] == 1203.80 and r["meses_entre_vencimento_e_pagamento"] == 1


def test_darf_multa_limitada_a_20_por_cento():
    r = calcular_darf(1000, "02/01/2026", "30/12/2026", selic_acumulada=10.5)  # 362 dias: 0,33% x 362 passaria de 100%
    assert r["taxa_multa"] == 0.20 and r["multa"] == 200.00 and r["juros"] == 115.00 and r["total"] == 1315.00


def test_darf_recusa_data_ruim_e_valor_zero():
    with pytest.raises(DadosInvalidos):
        calcular_darf(1000, "ontem", "15/10/2026")
    with pytest.raises(DadosInvalidos):
        calcular_darf(0, "20/08/2026", "15/10/2026")


# ------------------------------------------------------------------------------------------------------ feriados
def test_pascoa_e_sexta_feira_santa():
    assert [_pascoa(a) for a in (2024, 2025, 2026)] == [date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5)]
    assert date(2026, 4, 3) in feriados_nacionais(2026) and date(2026, 11, 20) in feriados_nacionais(2026)


# ------------------------------------------------------------------------------------- integração com o motor
def test_servico_conhece_os_novos_tipos_e_pergunta_o_que_falta():
    for tipo in ("prolabore", "gps", "das_mei", "darf"):
        assert tipo in servico.TIPOS_CALCULO
    assert servico.calcular("das_mei", {}, hoje=date(2026, 10, 15))["faltando"] == ["atividade_mei"]
    assert servico.calcular("darf", {"valor_principal": 100}, hoje=date(2026, 10, 15))["faltando"] == ["vencimento", "pagamento"]
    r = servico.calcular("darf", {"valor_principal": 1000, "vencimento": "20/08/2026", "pagamento": "15/10/2026"}, hoje=date(2026, 10, 15))
    assert r["status"] == "faltam_dados" and r["faltando"] == ["selic_acumulada"] and "SELIC" in r["pergunta"]
    sem_tabela = servico.calcular("das_mei", {"atividade_mei": "servicos", "competencia": "01/01/2010"}, hoje=date(2026, 10, 15))
    assert sem_tabela["status"] == "erro" and sem_tabela["codigo"] == "competencia_sem_tabela"  # nunca estima fora das tabelas


@pytest.mark.parametrize("tipo,dados,trecho", [
    ("prolabore", {"prolabore": 5000, "regime": "presumido"}, "Custo total para a empresa"),
    ("gps", {"tipo_gps": "baixa_renda"}, "Valor a pagar"),
    ("das_mei", {"atividade_mei": "servicos"}, "Valor a pagar"),
    ("darf", {"valor_principal": 1000, "vencimento": "28/08/2026", "pagamento": "10/09/2026"}, "Total a pagar"),
])
def test_cada_novo_tipo_gera_texto_e_pdf_com_o_resultado(tipo, dados, trecho):
    from io import BytesIO

    from pypdf import PdfReader

    r = servico.calcular(tipo, {**dados, "competencia": "01/10/2026"}, hoje=date(2026, 10, 15))
    assert r["status"] == "ok" and trecho in r["resumo"]
    pdf = gerar_pdf_calculo(tipo, r["resultado"])
    assert pdf.startswith(b"%PDF-")
    texto = "".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    assert trecho in texto


# ------------------------------------------------------------------------------------------------------- chat
HOJE = date(2026, 10, 15)


def _conversa(*mensagens):
    d, estado, saidas = DialogoCalculo(hoje=HOJE), {}, []
    for m in mensagens:
        saidas.append(d.processar(estado, m))
    return saidas


def test_chat_prolabore_no_simples():
    pergunta, final = _conversa("Calcular pró-labore", "pró-labore de R$ 5.000,00 no simples nacional")
    assert pergunta["status"] == "aguardando_dados" and "pró-labore" in pergunta["resposta"].lower()
    assert final["status"] == "ok" and "R$ 550,00" in final["resposta"] and "Contribuição patronal da empresa: R$ 0,00" in final["resposta"]


def test_chat_das_do_mei_pergunta_a_atividade():
    pergunta, final = _conversa("Calcular DAS do MEI", "serviços")
    assert pergunta["status"] == "aguardando_dados" and "atividade" in pergunta["resposta"].lower()
    assert final["status"] == "ok" and "R$ 86,05" in final["resposta"]


def test_chat_gps_pergunta_tipo_e_base():
    p1, p2, final = _conversa("Calcular GPS", "contribuinte individual", "R$ 4.000,00")
    assert "contribuinte" in p1["resposta"].lower() and "remuneração" in p2["resposta"].lower()
    assert final["status"] == "ok" and "R$ 800,00" in final["resposta"]


def test_chat_darf_pede_a_selic_quando_precisa_e_nao_chuta():
    pergunta, final = _conversa("DARF de R$ 1.000,00 venceu em 20/08/2026 pago em 15/10/2026", "0,9%")
    assert pergunta["status"] == "aguardando_dados" and "SELIC" in pergunta["resposta"]
    assert final["status"] == "ok" and "R$ 1.203,80" in final["resposta"] and "56 dia(s) de atraso" in final["resposta"]


def test_datas_do_darf_nao_viram_admissao_e_demissao_nem_13o():
    from contabil_agente.intelligence import extracao as ex

    msg = "DARF de R$ 1.000,00 venceu em 13/08/2026 pago em 15/10/2026"
    assert ex.detectar_tipo_calculo(msg) == "darf"  # "13" da data não vira 13º salário
    dados = ex.extrair_dados(msg)
    assert dados["vencimento"] == "2026-08-13" and dados["pagamento"] == "2026-10-15" and "data_admissao" not in dados


@pytest.mark.parametrize("mensagem", [
    "me explique o DARF",
    "o que é a GPS?",
    "como funciona o pró-labore",
    "para que serve o DAS do MEI",
])
def test_pergunta_conceitual_nao_vira_calculo_e_vai_para_a_conversa(mensagem):
    from contabil_agente.intelligence import extracao as ex

    assert ex.detectar_tipo_calculo(mensagem) is None


@pytest.mark.parametrize("mensagem,tipo", [
    ("Calcular DARF", "darf"),
    ("calcular pró-labore", "prolabore"),
    ("pró-labore de R$ 5.000,00", "prolabore"),
    ("quanto é o DAS do MEI?", "das_mei"),
    ("calcular a GPS", "gps"),
])
def test_pedido_de_calculo_dos_encargos_e_reconhecido(mensagem, tipo):
    from contabil_agente.intelligence import extracao as ex

    assert ex.detectar_tipo_calculo(mensagem) == tipo
