"""Agentes pela API (``/api/v1/agentes``) e o extrato do PGMEI pela fila, com cenários conferidos à mão."""

import json

from contabil_agente.rpa import ConfigPortalPGMEI
from contabil_agente.tests.portal_pgmei_falso import PgmeiFalso

from .test_api import client, entrar, llm  # noqa: F401
from .test_api_rpa import CPF, canal, chaves, consentir, portal, rpa  # noqa: F401  (fixtures: navegador, chaves, portal e API+worker)

CNPJ = "11.222.333/0001-81"
RESCISAO = {"salario": 3000, "tipo_rescisao": "sem justa causa", "data_admissao": "10/03/2023", "data_demissao": "15/09/2026",
            "aviso_previo": "indenizado", "saldo_fgts": 12000}


def chamar(c, agente, acao, dados, usuario="maria"):
    return c.post(f"/api/v1/agentes/{agente}/{acao}", json={"dados": dados}, headers=entrar(c, usuario))


# --------------------------------------------------------------------------- catálogo e permissões
def test_catalogo_lista_os_cinco_agentes_com_as_acoes(client):
    r = client.get("/api/v1/agentes", headers=entrar(client, "maria"))
    assert r.status_code == 200
    por_nome = {a["agente"]: a for a in r.json()["agentes"]}
    assert set(por_nome) == {"TaxAgent", "ValidationAgent", "ReconciliationAgent", "ComplianceAgent", "RPAAgent"}
    assert {"calcular", "tipos"} <= set(por_nome["TaxAgent"]["acoes"]) and "fechamento" in por_nome["ReconciliationAgent"]["acoes"]


def test_sem_login_ou_sem_permissao_nao_executa(client):
    assert client.get("/api/v1/agentes").status_code == 401
    assert client.post("/api/v1/agentes/TaxAgent/tipos", json={}).status_code == 401
    assert chamar(client, "TaxAgent", "tipos", {}, usuario="vera").status_code == 403  # perfil só de leitura


def test_agente_ou_acao_desconhecida_da_404(client):
    h = entrar(client, "maria")
    assert client.post("/api/v1/agentes/Fantasma/x", json={}, headers=h).status_code == 404
    assert client.post("/api/v1/agentes/TaxAgent/voar", json={}, headers=h).status_code == 404


# --------------------------------------------------------------------------- cada agente pela API
def test_taxagent_pela_api_calcula_a_rescisao_conferida_a_mao(client):
    r = chamar(client, "TaxAgent", "calcular", {"tipo": "rescisao", "dados": RESCISAO})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["resultado"]["total_liquido"] == 10253.48


def test_reconciliationagent_pela_api_aponta_divergencia(client):
    h = [{"total_proventos": "6000.00", "inss": "641.51", "irrf": "385.10"}]
    ok = chamar(client, "ReconciliationAgent", "fechamento", {"holerites": h, "guia_fgts": {"valor_fgts": "480.00"}, "gps": {"total": "2000"}, "darf": {"valor_principal": "385.10", "codigo_receita": "0561"}}).json()
    assert ok["veredito"] == "conciliado" and ok["conferencias_feitas"] == ["FGTS", "INSS", "IRRF"]
    ruim = chamar(client, "ReconciliationAgent", "fgts", {"holerites": h, "guia_fgts": {"valor_fgts": "400.00"}}).json()
    assert ruim["veredito"] == "divergente" and ruim["itens"][0]["diferenca"] == "-80.00"


def test_complianceagent_usa_a_lgpd_da_empresa_do_usuario(client):
    r = chamar(client, "ComplianceAgent", "base_legal", {"finalidade": "calculo_trabalhista"}).json()
    assert r["permitido"] is True and "contrato" in r["base_legal"]
    sem = chamar(client, "ComplianceAgent", "base_legal", {"finalidade": "consulta_extrato_fgts", "titular": CPF}).json()
    assert sem["permitido"] is False and "consentimento" in sem["motivo"]
    h = consentir(client)  # a empresa registra o consentimento do titular
    assert h
    com = chamar(client, "ComplianceAgent", "base_legal", {"finalidade": "consulta_extrato_fgts", "titular": CPF}).json()
    assert com["permitido"] is True
    ruim = chamar(client, "ComplianceAgent", "verificar", {"dados": {"cpf": "111.111.111-11", "salario": 500, "competencia": "2026-09"}}).json()
    assert ruim["conforme"] is False


def test_validationagent_pela_api_nao_grava_o_cpf_na_trilha(client):
    r = chamar(client, "ValidationAgent", "identificadores", {"itens": [{"tipo": "cpf", "valor": CPF}, {"tipo": "cnpj", "valor": CNPJ}]}).json()
    assert r["todos_validos"] is True
    trilha = json.dumps(client.app.state.audit.worm.ler("empresa_a"))
    assert "ValidationAgent.identificadores" in trilha and "52998224725" not in trilha and CPF not in trilha


# --------------------------------------------------------------------------- orquestração
def test_plano_orquestrado_calcula_o_fgts_e_concilia_com_a_guia(client):
    plano = {"passos": [
        {"agente": "TaxAgent", "acao": "calcular", "dados": {"tipo": "fgts", "dados": {"salario": 6000}}},
        {"agente": "ReconciliationAgent", "acao": "fgts", "dados": {"holerites": [{"total_proventos": 6000}], "guia_fgts": {"valor_fgts": "$1.resultado.fgts"}}},
    ]}
    r = client.post("/api/v1/agentes/orquestrar", json=plano, headers=entrar(client, "maria"))
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["passos"][1]["veredito"] == "conciliado"
    assert client.post("/api/v1/agentes/orquestrar", json={"passos": []}, headers=entrar(client, "maria")).status_code == 422
    onze = {"passos": [{"agente": "TaxAgent", "acao": "tipos"}] * 11}
    assert client.post("/api/v1/agentes/orquestrar", json=onze, headers=entrar(client, "maria")).status_code == 422


# --------------------------------------------------------------------------- PGMEI pela fila
def _com_pgmei(rpa, canal):
    pgmei = PgmeiFalso()
    rpa.ctx.config_pgmei = ConfigPortalPGMEI(url=pgmei.url, headless=True, canal=canal, timeout_humano_s=20, timeout_navegacao_s=20, timeout_download_s=10, espera_elemento_s=3)
    return pgmei


def test_extrato_do_pgmei_de_ponta_a_ponta_pela_rota_e_pelo_agente(rpa, canal):
    pgmei = _com_pgmei(rpa, canal)
    try:
        h = entrar(rpa, "maria")
        r = rpa.post("/api/v1/rpa/pgmei", json={"cnpj": CNPJ, "ano": 2025}, headers=h)
        assert r.status_code == 202, r.text
        job = rpa.get(f"/api/v1/rpa/jobs/{r.json()['job_id']}", headers=h).json()
        assert job["estado"] == "CONCLUIDO", job
        assert job["resultado"]["tipo"] == "DAS" and job["resultado"]["estado"] == "ARCHIVED"
        assert rpa.cliques and pgmei.anos_pedidos == ["2025"]  # a "pessoa" resolveu o hCaptcha e o robô escolheu o ano

        # o mesmo caminho, agora pelo RPAAgent
        via_agente = chamar(rpa, "RPAAgent", "solicitar_extrato", {"portal": "pgmei", "documento": CNPJ, "ano": 2026}).json()
        assert via_agente["status"] == "ok" and via_agente["estado"] in ("RECEBIDO", "CONCLUIDO", "EXECUTANDO", "AGUARDANDO_HUMANO")
        estado = chamar(rpa, "RPAAgent", "estado", {"job_id": via_agente["job_id"]}).json()
        assert estado["trabalho"]["estado"] == "CONCLUIDO" and pgmei.anos_pedidos == ["2025", "2026"]
    finally:
        pgmei.parar()


def test_rpaagent_recusa_cnpj_invalido_e_fgts_sem_consentimento_com_a_mensagem_certa(rpa):
    ruim = chamar(rpa, "RPAAgent", "solicitar_extrato", {"portal": "pgmei", "documento": "11.222.333/0001-82"}).json()
    assert ruim["status"] == "erro" and "CNPJ inválido" in ruim["mensagem"]
    sem = chamar(rpa, "RPAAgent", "solicitar_extrato", {"portal": "fgts", "documento": CPF}).json()
    assert sem["status"] == "erro" and "consentimento" in sem["mensagem"]
    assert rpa.cliques == []  # nada foi para a fila nem abriu navegador


def test_cnpj_nunca_aparece_na_trilha_nem_no_status_do_pgmei(rpa, canal, tmp_path):
    pgmei = _com_pgmei(rpa, canal)
    try:
        h = entrar(rpa, "maria")
        job_id = rpa.post("/api/v1/rpa/pgmei", json={"cnpj": CNPJ}, headers=h).json()["job_id"]
    finally:
        pgmei.parar()
    bruto = open(tmp_path / "audit" / "empresa_a.worm.jsonl", "rb").read() + open(rpa.app.state.rpa_status.db_path, "rb").read()
    assert b"11222333000181" not in bruto and CNPJ.encode() not in bruto
    assert rpa.get(f"/api/v1/rpa/jobs/{job_id}", headers=h).json()["estado"] == "CONCLUIDO"
