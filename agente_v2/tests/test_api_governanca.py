"""Governança, observabilidade e proteções HTTP pela API."""

from decimal import Decimal

import pytest

from contabil_agente.governance_manager import GovernanceManager
from contabil_agente.middleware.limite_de_uso import LimiteDeUso

from .test_api import client, entrar, llm  # noqa: F401


def decisao(client, headers, valor="80000", tipo="rescisao"):
    return client.post("/api/v1/governanca/decisoes", json={"tipo": tipo, "valor": valor, "descricao": "rescisão X", "referencia": "TRCT-1"}, headers=headers)


@pytest.fixture()
def gov_client(client):
    client.app.state.governanca.limites = {"rescisao": Decimal("50000")}
    client.app.state.auth.criar_usuario("ana", "Senha-Forte-123", "empresa_a", ["accountant"])
    return client


def test_decisao_pequena_e_automatica_e_assinada(gov_client):
    r = decisao(gov_client, entrar(gov_client), "10000")
    assert r.status_code == 201 and r.json()["estado"] == "APROVADA_AUTOMATICAMENTE"
    ver = gov_client.get(f"/api/v1/governanca/decisoes/{r.json()['id']}", headers=entrar(gov_client)).json()
    assert ver["assinatura_valida"] is True


def test_decisao_grande_exige_outra_pessoa(gov_client):
    maria = entrar(gov_client, "maria")
    d = decisao(gov_client, maria).json()
    assert d["estado"] == "PENDENTE"
    propria = gov_client.post(f"/api/v1/governanca/decisoes/{d['id']}/aprovar", json={}, headers=maria)
    assert propria.status_code == 403 and "duas pessoas" in propria.json()["detail"]
    ana = entrar(gov_client, "ana")
    assert [x["id"] for x in gov_client.get("/api/v1/governanca/pendentes", headers=ana).json()["pendentes"]] == [d["id"]]
    ok = gov_client.post(f"/api/v1/governanca/decisoes/{d['id']}/aprovar", json={"comentario": "conferi"}, headers=ana)
    assert ok.status_code == 200 and ok.json()["estado"] == "APROVADA" and ok.json()["aprovador"] != d["solicitante"]
    assert gov_client.post(f"/api/v1/governanca/decisoes/{d['id']}/rejeitar", json={}, headers=ana).status_code == 409


def test_rejeicao_e_validacoes(gov_client):
    maria, ana = entrar(gov_client, "maria"), entrar(gov_client, "ana")
    d = decisao(gov_client, maria).json()
    assert gov_client.post(f"/api/v1/governanca/decisoes/{d['id']}/rejeitar", json={"comentario": "valor errado"}, headers=ana).json()["estado"] == "REJEITADA"
    assert decisao(gov_client, maria, "abc").status_code == 422
    assert decisao(gov_client, maria, "-5").status_code == 422


def test_governanca_respeita_login_permissao_e_tenant(gov_client):
    assert gov_client.get("/api/v1/governanca/pendentes").status_code == 401
    assert gov_client.get("/api/v1/governanca/pendentes", headers=entrar(gov_client, "vera")).status_code == 403
    d = decisao(gov_client, entrar(gov_client, "maria")).json()
    joao = entrar(gov_client, "joao")  # outro tenant
    assert gov_client.get(f"/api/v1/governanca/decisoes/{d['id']}", headers=joao).status_code == 404
    assert gov_client.post(f"/api/v1/governanca/decisoes/{d['id']}/aprovar", json={}, headers=joao).status_code == 404


def test_decisao_adulterada_no_banco_nao_pode_ser_aprovada(gov_client):
    import sqlite3

    d = decisao(gov_client, entrar(gov_client, "maria")).json()
    con = sqlite3.connect(gov_client.app.state.governanca.db_path)
    con.execute("UPDATE decisoes SET valor = '1.00' WHERE id = ?", (d["id"],))
    con.commit()
    con.close()
    ana = entrar(gov_client, "ana")
    assert gov_client.get(f"/api/v1/governanca/decisoes/{d['id']}", headers=ana).json()["assinatura_valida"] is False
    assert gov_client.post(f"/api/v1/governanca/decisoes/{d['id']}/aprovar", json={}, headers=ana).status_code == 409


def test_governanca_na_trilha_worm(gov_client):
    d = decisao(gov_client, entrar(gov_client, "maria")).json()
    eventos = [e["evento"] for e in gov_client.app.state.audit.worm.ler("empresa_a")]
    assert "governanca.decisao_registrada" in eventos and gov_client.app.state.audit.worm.verificar("empresa_a").ok
    del d


# ---------------------------------------------------------------- observabilidade
def test_toda_resposta_tem_request_id_e_o_do_cliente_e_aproveitado_se_for_valido(client):
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) == 32
    assert client.get("/health", headers={"X-Request-ID": "meu-id-1234567"}).headers["x-request-id"] == "meu-id-1234567"
    assert client.get("/health", headers={"X-Request-ID": "x\ny<script>"}).headers["x-request-id"] != "x\ny<script>"


def test_metricas_usam_o_molde_da_rota_e_nao_a_url_com_dados(client):
    h = entrar(client)
    client.get("/api/chat/sessao-com-dado-pessoal-529.982.247-25", headers=h)
    corpo = client.get("/metrics").text
    assert 'rota="/api/chat/{session_id}"' in corpo and "529.982.247-25" not in corpo
    assert "agente_http_latencia_segundos_bucket" in corpo


def test_headers_de_seguranca_completos_e_cors_fechado_por_padrao(client):
    r = client.get("/health", headers={"Origin": "https://site-malicioso.com"})
    assert "access-control-allow-origin" not in r.headers
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["permissions-policy"].startswith("camera=()") and "strict-transport-security" not in r.headers


def test_hsts_so_quando_https_only(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agente_v2.main import create_app

    from .test_api import nova_auditoria, novo_auth, novo_dispatcher
    from contabil_agente.chat import ChatEngine, ChatStore

    monkeypatch.setenv("HTTPS_ONLY", "1")
    app = create_app(auth=novo_auth(tmp_path), engine=ChatEngine(llm=None), store=ChatStore(str(tmp_path / "c.db")), audit=nova_auditoria(tmp_path), dispatcher=novo_dispatcher(tmp_path))
    assert "max-age" in TestClient(app).get("/health").headers["strict-transport-security"]


def test_ready_confere_disco_e_vault(client, monkeypatch):
    assert client.get("/ready").status_code == 200
    import agente_v2.main as m

    monkeypatch.setattr(m, "readiness_check", lambda *a, **k: {"status": "unavailable", "reason": "disk_full"})
    r = client.get("/ready")
    assert r.status_code == 503 and "disk_full" in r.json()["detail"]


# ------------------------------------------------------------------- limite de uso
def test_limite_de_uso_janela_deslizante():
    t = [0.0]
    lim = LimiteDeUso(maximo=3, janela_segundos=10, relogio=lambda: t[0])
    assert [lim.permitir("a") for _ in range(4)] == [True, True, True, False]
    assert lim.permitir("b") is True  # outra chave
    t[0] = 11
    assert lim.permitir("a") is True
    with pytest.raises(ValueError):
        LimiteDeUso(0, 10)


def test_login_tem_limite_por_ip(client):
    codigos = [client.post("/token", data={"username": "x", "password": "y"}).status_code for _ in range(12)]
    assert 429 in codigos and codigos[0] == 401
