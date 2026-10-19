"""Os cinco agentes e o orquestrador, com cenários conferidos à mão (nada de resposta simulada de LLM)."""

import base64
from datetime import date

import pytest

from contabil_agente.agentes import (
    AcaoDesconhecida, AgenteErro, ComplianceAgent, OrquestradorDeAgentes, RPAAgent, ReconciliationAgent, TaxAgent, ValidationAgent,
)

from . import amostras_documentos as am

HOJE = date(2026, 10, 15)
CPF = "529.982.247-25"
CNPJ = "11.222.333/0001-81"


# ------------------------------------------------------------------------------ TaxAgent
def test_taxagent_calcula_a_rescisao_do_cenario_conferido_a_mao():
    r = TaxAgent(hoje=HOJE).executar("calcular", {"tipo": "rescisao", "dados": {
        "salario": 3000, "tipo_rescisao": "sem justa causa", "data_admissao": "10/03/2023", "data_demissao": "15/09/2026",
        "aviso_previo": "indenizado", "saldo_fgts": 12000}})
    assert r["status"] == "ok" and r["agente"] == "TaxAgent"
    assert r["resultado"]["total_proventos"] == 10566.67 and r["resultado"]["total_liquido"] == 10253.48
    assert r["resultado"]["fgts"]["multa"] == 5052.8


def test_taxagent_pergunta_o_que_falta_em_vez_de_inventar():
    r = TaxAgent(hoje=HOJE).executar("calcular", {"tipo": "rescisao", "dados": {"salario": 3000}})
    assert r["status"] == "faltam_dados" and "tipo_rescisao" in r["faltando"] and r["pergunta"]


def test_taxagent_lista_os_calculos_e_valida_o_pedido():
    ag = TaxAgent(hoje=HOJE)
    assert {"rescisao", "ferias", "gps", "das_mei", "darf", "prolabore"} <= set(ag.executar("tipos")["tipos"])
    assert ag.executar("calcular", {"tipo": "rescisao"})["status"] == "erro"  # falta o campo "dados"
    assert ag.executar("calcular", {"tipo": "nao_existe", "dados": {"x": 1}})["status"] == "erro"


# ------------------------------------------------------------------------ ReconciliationAgent
HOLERITES = [
    {"total_proventos": "6000.00", "inss": "641.51", "irrf": "385.10", "fgts": "480.00"},
    {"total_proventos": "3000.00", "inss": "300.00", "irrf": "0.00", "fgts": "240.00"},
]


def test_conciliacao_fgts_bate_quando_a_guia_e_8_por_cento_da_folha():
    r = ReconciliationAgent().executar("fgts", {"holerites": HOLERITES, "guia_fgts": {"valor_fgts": "720.00"}})
    assert r["status"] == "ok" and r["veredito"] == "conciliado"
    assert [i["esperado"] for i in r["itens"]] == ["720.00", "720.00"] and all(i["ok"] for i in r["itens"])


def test_conciliacao_fgts_aponta_a_diferenca_em_reais():
    r = ReconciliationAgent().executar("fgts", {"holerites": HOLERITES, "guia_fgts": {"valor_fgts": "700.00"}})
    assert r["veredito"] == "divergente"
    assert r["itens"][0]["diferenca"] == "-20.00" and r["itens"][0]["ok"] is False


def test_conciliacao_inss_a_gps_precisa_cobrir_ao_menos_o_retido():
    ag = ReconciliationAgent()
    retido = 641.51 + 300.00
    ok = ag.executar("inss", {"holerites": HOLERITES, "gps": {"total": str(round(retido + 1200, 2))}})  # retido + parte patronal
    assert ok["veredito"] == "conciliado"
    curta = ag.executar("inss", {"holerites": HOLERITES, "gps": {"total": "900.00"}})
    assert curta["veredito"] == "divergente" and curta["itens"][0]["diferenca"] == "-41.51"


def test_conciliacao_irrf_com_darf_do_trabalho_e_aviso_de_codigo_errado():
    ag = ReconciliationAgent()
    ok = ag.executar("irrf", {"holerites": HOLERITES, "darf": {"valor_principal": "385.10", "codigo_receita": "0561"}})
    assert ok["veredito"] == "conciliado" and ok["itens"][0]["observacao"] == ""
    outro = ag.executar("irrf", {"holerites": HOLERITES, "darf": {"valor_principal": "385.10", "codigo_receita": "1708"}})
    assert "0561" in outro["itens"][0]["observacao"]


def test_conciliacao_sem_documentos_diz_sem_base_e_nao_da_o_visto():
    r = ReconciliationAgent().executar("fechamento", {"holerites": HOLERITES})
    assert r["veredito"] == "sem_base" and r["itens"] == []
    assert ReconciliationAgent().executar("fgts", {"guia_fgts": {"valor_fgts": "1"}})["veredito"] == "sem_base"


def test_conciliacao_fechamento_junta_as_tres_e_lista_as_divergencias():
    r = ReconciliationAgent().executar("fechamento", {
        "holerites": HOLERITES, "guia_fgts": {"valor_fgts": "720.00"},
        "gps": {"total": "900.00"}, "darf": {"valor_principal": "385.10", "codigo_receita": "0561"}})
    assert r["veredito"] == "divergente" and r["conferencias_feitas"] == ["FGTS", "INSS", "IRRF"]
    assert len(r["divergencias"]) == 1 and r["divergencias"][0]["conferencia"].startswith("INSS")


def test_conciliacao_valida_o_formato_dos_documentos():
    assert ReconciliationAgent().executar("fgts", {"holerites": "x", "guia_fgts": {}})["status"] == "erro"
    assert ReconciliationAgent().executar("fgts", {"holerites": [{"total_proventos": "abc"}], "guia_fgts": {"valor_fgts": "1"}})["status"] == "erro"


# ------------------------------------------------------------------------------ ValidationAgent
def test_validationagent_confere_digitos_e_nao_devolve_o_identificador_inteiro():
    r = ValidationAgent().executar("identificadores", {"itens": [
        {"tipo": "cpf", "valor": CPF}, {"tipo": "cpf", "valor": "529.982.247-24"}, {"tipo": "cnpj", "valor": CNPJ}, {"tipo": "pis", "valor": "123.45678.91-9"}]})
    assert [i["valido"] for i in r["itens"]] == [True, False, True, True] and r["todos_validos"] is False
    assert "52998224725" not in str(r) and CPF not in str(r)


def test_validationagent_recusa_tipo_desconhecido_e_processa_um_documento_de_verdade():
    ag = ValidationAgent()
    assert ag.executar("identificadores", {"itens": [{"tipo": "rg", "valor": "1"}]})["status"] == "erro"
    r = ag.executar("documento", {"conteudo_base64": base64.b64encode(am.HOLERITE.encode()).decode(), "nome": "holerite.txt"})
    assert r["status"] == "ok" and r["tipo"] == "HOLERITE" and r["extraido"]["liquido"] == "4973.39"
    assert ag.executar("documento", {"conteudo_base64": "isto nao e base64!!"})["status"] == "erro"


# ------------------------------------------------------------------------------ ComplianceAgent
def test_complianceagent_bloqueia_cpf_invalido_e_salario_abaixo_do_minimo():
    ag = ComplianceAgent()
    ok = ag.executar("verificar", {"dados": {"cpf": CPF, "salario": 3000, "competencia": "2026-09"}})
    assert ok["status"] == "ok" and ok["conforme"] is True and ok["issues"] == []
    ruim = ag.executar("verificar", {"dados": {"cpf": "111.111.111-11", "salario": 500, "competencia": "2026-09"}})
    assert ruim["conforme"] is False and {i["field"] for i in ruim["issues"]} == {"cpf", "salario"}


def test_complianceagent_base_legal_exige_servico_de_lgpd_e_lista_finalidades():
    assert ComplianceAgent().executar("base_legal", {"finalidade": "calculo_trabalhista"})["status"] == "erro"
    r = ComplianceAgent().executar("finalidades", {})
    assert any(f["codigo"] == "calculo_trabalhista" for f in r["finalidades"])


# ------------------------------------------------------------------------------ RPAAgent
def test_rpaagent_valida_portal_e_ano_e_repassa_o_pedido():
    pedidos = []
    ag = RPAAgent(lambda portal, doc, ano: (pedidos.append((portal, doc, ano)), {"job_id": "j1", "estado": "RECEBIDO"})[1], lambda job: {"id": job} if job == "j1" else None)
    assert ag.executar("solicitar_extrato", {"portal": "pgmei", "documento": CNPJ, "ano": 2026})["job_id"] == "j1"
    assert pedidos == [("pgmei", CNPJ, 2026)]
    assert ag.executar("solicitar_extrato", {"portal": "esocial", "documento": CNPJ})["status"] == "erro"
    assert ag.executar("solicitar_extrato", {"portal": "nfe", "documento": "3526 0911"})["job_id"] == "j1" and pedidos[-1][0] == "nfe"
    assert ag.executar("solicitar_extrato", {"portal": "fgts", "documento": CPF, "ano": "2026"})["status"] == "erro"
    assert ag.executar("estado", {"job_id": "j1"})["trabalho"] == {"id": "j1"} and ag.executar("estado", {"job_id": "zz"})["status"] == "erro"
    assert [p["portal"] for p in ag.executar("portais", {})["portais"]] == ["fgts", "pgmei", "nfe"]


# ------------------------------------------------------------------------------ orquestrador
def _orq():
    return OrquestradorDeAgentes({"TaxAgent": TaxAgent(hoje=HOJE), "ReconciliationAgent": ReconciliationAgent(), "ComplianceAgent": ComplianceAgent()})


def test_orquestrador_passa_o_resultado_de_um_passo_ao_seguinte_mantendo_o_tipo():
    r = _orq().executar([
        {"agente": "TaxAgent", "acao": "calcular", "dados": {"tipo": "fgts", "dados": {"salario": 6000}}},
        {"agente": "ReconciliationAgent", "acao": "fgts", "dados": {
            "holerites": [{"total_proventos": 6000}], "guia_fgts": {"valor_fgts": "$1.resultado.fgts"}}},
    ])
    assert r["status"] == "ok", r
    assert r["passos"][0]["resultado"]["fgts"] == 480.0 and r["passos"][1]["veredito"] == "conciliado"


def test_orquestrador_para_no_primeiro_passo_com_erro_e_pode_continuar_se_pedido():
    plano = [
        {"agente": "TaxAgent", "acao": "calcular", "dados": {"tipo": "rescisao", "dados": {"salario": 3000}}},  # faltam dados
        {"agente": "TaxAgent", "acao": "tipos"},
    ]
    parou = _orq().executar(plano)
    assert parou["status"] == "interrompido" and parou["interrompido_no_passo"] == 1 and len(parou["passos"]) == 1
    plano[0]["continuar_em_erro"] = True
    seguiu = _orq().executar(plano)
    assert seguiu["status"] == "ok_com_erros" and len(seguiu["passos"]) == 2


def test_orquestrador_recusa_plano_ruim():
    orq = _orq()
    with pytest.raises(AgenteErro):
        orq.executar([])
    with pytest.raises(AgenteErro):
        orq.executar([{"agente": "TaxAgent"}])
    with pytest.raises(AgenteErro):
        orq.executar([{"agente": "TaxAgent", "acao": "tipos"}] * 11)
    r = orq.executar([{"agente": "Fantasma", "acao": "x"}])
    assert r["status"] == "interrompido" and "desconhecido" in r["passos"][0]["mensagem"]
    r2 = orq.executar([{"agente": "TaxAgent", "acao": "tipos", "dados": {"x": "$3.y"}}])
    assert r2["passos"][0]["status"] == "erro" and "ainda não rodou" in r2["passos"][0]["mensagem"]


def test_acao_inexistente_levanta():
    with pytest.raises(AcaoDesconhecida):
        TaxAgent().executar("voar", {})
