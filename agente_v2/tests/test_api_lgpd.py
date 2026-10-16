"""LGPD pela API: IA externa só com consentimento, consentimento por titular, retenção e exclusão."""

import json
import os
import time

from .test_api import client, entrar, llm  # noqa: F401

CPF = "529.982.247-25"
DIA = 86400


def test_ia_externa_so_funciona_com_consentimento_do_tenant(client, llm):
    # empresa_a tem consentimento (fixture); empresa_b não
    ok = client.post("/api/chat", json={"message": "explique o DARF"}, headers=entrar(client, "maria")).json()
    assert ok["response"] == "Resposta de teste do LLM." and len(llm.recebido) == 1
    sem = client.post("/api/chat", json={"message": "explique o DARF"}, headers=entrar(client, "joao")).json()
    assert "consentimento" in sem["response"] and len(llm.recebido) == 1  # nada foi enviado ao provedor


def test_calculo_continua_funcionando_sem_consentimento_de_ia(client):
    r = client.post("/api/chat", json={"message": "calcular INSS de um salário de R$ 5.000,00"}, headers=entrar(client, "joao")).json()
    assert r["dados_calculados"]["inss"] == 501.51


def test_administrador_registra_e_revoga_o_consentimento_de_sistema(client, llm):
    adm_b = client.app.state.auth.criar_usuario("admin_b", "Senha-Forte-123", "empresa_b", ["tenant_admin"])
    h = entrar(client, "admin_b")
    r = client.post("/api/v1/lgpd/consentimentos", json={"finalidade": "envio_a_provedor_de_ia", "concedido": True}, headers=h)
    assert r.status_code == 201
    joao = entrar(client, "joao")
    assert client.post("/api/chat", json={"message": "explique o DARF"}, headers=joao).json()["response"] == "Resposta de teste do LLM."
    client.post("/api/v1/lgpd/consentimentos", json={"finalidade": "envio_a_provedor_de_ia", "concedido": False}, headers=h)
    assert "consentimento" in client.post("/api/chat", json={"message": "explique o DARF"}, headers=joao).json()["response"]
    hist = client.get("/api/v1/lgpd/consentimentos", headers=h).json()["historico"]
    assert [x["concedido"] for x in hist] == [True, False]
    del adm_b


def test_so_o_admin_registra_consentimento_de_sistema(client):
    r = client.post("/api/v1/lgpd/consentimentos", json={"finalidade": "envio_a_provedor_de_ia", "concedido": True}, headers=entrar(client, "joao"))
    assert r.status_code == 403
    ok = client.post("/api/v1/lgpd/consentimentos", json={"finalidade": "consulta_extrato_fgts", "concedido": True, "titular": CPF}, headers=entrar(client, "joao"))
    assert ok.status_code == 201


def test_finalidade_desconhecida_e_recusada_e_a_lista_traz_a_base_legal(client):
    h = entrar(client)
    assert client.post("/api/v1/lgpd/consentimentos", json={"finalidade": "inventada", "concedido": True, "titular": CPF}, headers=h).status_code == 422
    lista = client.get("/api/v1/lgpd/finalidades", headers=h).json()["finalidades"]
    assert any(f["codigo"] == "calculo_trabalhista" and "art. 7º, V" in f["base_legal"] for f in lista)


def test_documento_processado_sem_consentimento_roda_sem_ia_e_avisa(client, tmp_path):
    from .test_api_documentos import HOLERITE, enviar

    client.app.state.dispatcher.worker_llm = object()  # existe um provedor configurado
    r = enviar(client, entrar(client, "joao"), HOLERITE.encode()).json()
    assert r["agentes"]["worker"] == "deterministico" and any("consentimento" in a for a in r["avisos"])


def test_retencao_politica_e_execucao(client, tmp_path):
    h = entrar(client, "admin")
    assert client.get("/api/v1/lgpd/retencao", headers=h).json()["prazos_em_dias"]["auditoria"] is None
    pasta = tmp_path / "arquivo" / "empresa_a" / "HOLERITE"
    pasta.mkdir(parents=True)
    velho = pasta / "velho.json"
    velho.write_text("{}")
    antigo = time.time() - 6 * 365 * DIA
    os.utime(velho, (antigo, antigo))
    client.app.state.lgpd.raiz_arquivo = tmp_path / "arquivo"
    r = client.post("/api/v1/lgpd/retencao/executar", headers=h)
    assert r.status_code == 200 and r.json()["removidos"]["documentos"] == 1 and not velho.exists()
    assert client.post("/api/v1/lgpd/retencao/executar", headers=entrar(client, "maria")).status_code == 403


def test_exclusao_do_titular_pela_api(client, tmp_path):
    pasta = tmp_path / "arquivo" / "empresa_a" / "HOLERITE"
    pasta.mkdir(parents=True)
    velho, recente = pasta / "velho.json", pasta / "recente.json"
    for arq in (velho, recente):
        arq.write_text(json.dumps({"cpf": CPF}))
    antigo = time.time() - 6 * 365 * DIA
    os.utime(velho, (antigo, antigo))
    client.app.state.lgpd.raiz_arquivo = tmp_path / "arquivo"
    adm = entrar(client, "admin")
    r = client.request("DELETE", "/api/v1/lgpd/titular", json={"documento": "52998224725"}, headers=adm)
    assert r.status_code == 200
    j = r.json()
    assert len(j["apagados"]) == 1 and len(j["retidos"]) == 1 and recente.exists() and not velho.exists()
    assert client.request("DELETE", "/api/v1/lgpd/titular", json={"documento": "123"}, headers=adm).status_code == 422
    assert client.request("DELETE", "/api/v1/lgpd/titular", json={"documento": CPF}, headers=entrar(client, "maria")).status_code == 403


def test_exclusao_fica_na_trilha_sem_o_cpf(client, tmp_path):
    adm = entrar(client, "admin")
    client.request("DELETE", "/api/v1/lgpd/titular", json={"documento": CPF}, headers=adm)
    bruto = (tmp_path / "audit" / "empresa_a.worm.jsonl").read_text(encoding="utf-8")
    assert "lgpd.exclusao" in bruto and "52998224725" not in bruto and CPF not in bruto
    assert client.get("/api/v1/auditoria/verificar", headers=adm).json()["ok"] is True
