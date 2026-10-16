"""RPA e lote pela API + Celery (modo eager): CPF cifrado no broker, consentimento, pausa de humano e status."""

import json

import pytest

from contabil_agente.pipeline import ArquivoDestino, DocumentDispatcher, HistoricoDocumentos
from contabil_agente.rpa import ConfigPortalFGTS
from contabil_agente.rpa.estado import StatusStore
from contabil_agente.security import pqc
from contabil_agente.tarefas import celery_app
from contabil_agente.tarefas.contexto import Contexto, definir_contexto
from contabil_agente.tests.portal_fgts_falso import PortalFalso
from contabil_agente.tests.test_rpa_fgts import canal  # noqa: F401  (fixture: navegador disponível)

from .test_api import client, entrar, llm  # noqa: F401
from .test_api_documentos import HOLERITE

CPF = "529.982.247-25"


@pytest.fixture()
def chaves():
    return pqc.gerar_chaves_hibridas()


@pytest.fixture()
def portal():
    p = PortalFalso()
    yield p
    p.parar()


@pytest.fixture()
def rpa(client, chaves, portal, canal, tmp_path):
    """API + tarefas no mesmo processo (Celery eager), contra o portal falso, com 'humano' clicando no captcha."""
    app = client.app
    app.state.rpa_chave_publica = chaves.publica()
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    cliques = []
    ctx = Contexto(
        audit=app.state.audit.worm, dispatcher=app.state.dispatcher, lgpd=app.state.lgpd, status=app.state.rpa_status,
        config_fgts=ConfigPortalFGTS(url=portal.url, headless=True, canal=canal, timeout_humano_s=20, timeout_navegacao_s=20, timeout_download_s=10),
        pasta_de_trabalho=tmp_path / "rpa", chave_privada_rpa=chaves.privada(), chave_hash=app.state.lgpd._chave_hash,
        ao_pausar=lambda motivo, seletor, page: (cliques.append(motivo), page.click("#humano-ok")),
    )
    definir_contexto(ctx)
    client.cliques, client.ctx = cliques, ctx
    yield client
    definir_contexto(None)
    celery_app.conf.task_always_eager = False


def consentir(client, cpf=CPF, concedido=True):
    h = entrar(client, "maria")
    r = client.post("/api/v1/lgpd/consentimentos", json={"finalidade": "consulta_extrato_fgts", "concedido": concedido, "titular": cpf}, headers=h)
    assert r.status_code == 201
    return h


# ------------------------------------------------------------------------------ FGTS
def test_extrato_fgts_de_ponta_a_ponta(rpa, portal):
    h = consentir(rpa)
    r = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=h)
    assert r.status_code == 202, r.text
    job = rpa.get(f"/api/v1/rpa/jobs/{r.json()['job_id']}", headers=h).json()
    assert job["estado"] == "CONCLUIDO", job
    assert job["resultado"]["tipo"] == "FGTS_EXTRATO" and job["resultado"]["estado"] == "ARCHIVED"
    assert job["resultado"]["audit_trail_id"].startswith("empresa_a:") and len(job["resultado"]["sha256"]) == 64
    assert rpa.cliques  # o robô pausou e a "pessoa" resolveu o captcha
    assert any("52998224725" in c for c in portal.cpfs_recebidos)


def test_o_cpf_nunca_viaja_em_claro_no_broker_nem_fica_no_status_ou_na_trilha(rpa, tmp_path, monkeypatch):
    from contabil_agente.tarefas import rpa as tarefa

    capturado = []
    original = tarefa.extrato_fgts.apply_async
    monkeypatch.setattr(tarefa.extrato_fgts, "apply_async", lambda args=None, **kw: (capturado.append(args), original(args=args, **kw))[1])
    h = consentir(rpa)
    job_id = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=h).json()["job_id"]
    msg = json.dumps(capturado)
    assert "52998224725" not in msg and CPF not in msg and "ML-KEM-768" in msg
    rpa_db = open(rpa.app.state.rpa_status.db_path, "rb").read()
    trilha = open(tmp_path / "audit" / "empresa_a.worm.jsonl", "rb").read()
    for bruto in (rpa_db, trilha):
        assert b"52998224725" not in bruto and CPF.encode() not in bruto
    assert rpa.get(f"/api/v1/rpa/jobs/{job_id}", headers=h).json()["estado"] == "CONCLUIDO"


def test_sem_consentimento_do_titular_nem_enfileira(rpa):
    r = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=entrar(rpa, "maria"))
    assert r.status_code == 403 and "consentimento" in r.json()["detail"]
    assert rpa.cliques == []


def test_consentimento_revogado_depois_de_enfileirar_e_respeitado_no_worker(rpa, chaves):
    from contabil_agente.tarefas import rpa as tarefa

    h = consentir(rpa)
    job_id = rpa.app.state.rpa_status.criar("empresa_a", "u", "extrato_fgts")
    env = tarefa.envelope_do_cpf(chaves.publica(), CPF, "empresa_a", job_id)
    consentir(rpa, concedido=False)  # revoga antes do worker rodar
    r = tarefa.extrato_fgts.apply(args=[job_id, "empresa_a", "u", env]).get()
    assert r["status"] == "falhou" and "consentimento" in r["mensagem"]
    assert rpa.cliques == []
    del h


def test_cpf_invalido_422_e_sem_chave_do_rpa_503(rpa):
    h = consentir(rpa)
    assert rpa.post("/api/v1/rpa/fgts", json={"cpf": "111.111.111-11"}, headers=h).status_code == 422
    rpa.app.state.rpa_chave_publica = None
    r = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=h)
    assert r.status_code == 503 and "RPA_PQC_PUBLIC_KEY" in r.json()["detail"]


def test_sem_login_ou_permissao_nao_enfileira(rpa):
    assert rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}).status_code == 401
    assert rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=entrar(rpa, "vera")).status_code == 403


def test_status_do_job_e_isolado_por_tenant(rpa):
    h = consentir(rpa)
    job_id = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=h).json()["job_id"]
    assert rpa.get(f"/api/v1/rpa/jobs/{job_id}", headers=entrar(rpa, "joao")).status_code == 404
    assert rpa.get("/api/v1/rpa/jobs/inexistente", headers=h).status_code == 404


def test_worker_com_chave_errada_ou_envelope_adulterado_falha_sem_abrir_o_navegador(rpa, chaves):
    from contabil_agente.tarefas import rpa as tarefa

    consentir(rpa)
    status = rpa.app.state.rpa_status
    job1 = status.criar("empresa_a", "u", "extrato_fgts")
    env = tarefa.envelope_do_cpf(chaves.publica(), CPF, "empresa_a", job1)
    rpa.ctx.chave_privada_rpa = pqc.gerar_chaves_hibridas().privada()
    assert "decifrar" in tarefa.extrato_fgts.apply(args=[job1, "empresa_a", "u", env]).get()["mensagem"]
    rpa.ctx.chave_privada_rpa = chaves.privada()
    job2 = status.criar("empresa_a", "u", "extrato_fgts")
    outro_job = tarefa.extrato_fgts.apply(args=[job2, "empresa_a", "u", env]).get()  # envelope de outro job: aad diferente
    assert outro_job["status"] == "falhou" and rpa.cliques == []


def test_broker_fora_do_ar_vira_503_e_o_job_fica_como_falhou(rpa, monkeypatch):
    from contabil_agente.tarefas import rpa as tarefa

    def quebrado(*a, **k):
        raise ConnectionError("redis fora")

    monkeypatch.setattr(tarefa.extrato_fgts, "apply_async", quebrado)
    h = consentir(rpa)
    r = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=h)
    assert r.status_code == 503 and "Redis" in r.json()["detail"]


def test_portal_sem_resposta_de_humano_termina_falhou(rpa, portal):
    rpa.ctx.ao_pausar = lambda *a: None  # ninguém resolve
    rpa.ctx.config_fgts = rpa.ctx.config_fgts.com(timeout_humano_s=3)
    h = consentir(rpa)
    job_id = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=h).json()["job_id"]
    job = rpa.get(f"/api/v1/rpa/jobs/{job_id}", headers=h).json()
    assert job["estado"] == "FALHOU" and "captcha" in job["mensagem"]


def test_estados_do_status_nao_voltam_atras(tmp_path):
    s = StatusStore(tmp_path / "s.db")
    j = s.criar("t", "u", "x")
    s.atualizar(j, "EXECUTANDO")
    s.atualizar(j, "CONCLUIDO", "ok", {"a": 1})
    s.atualizar(j, "EXECUTANDO", "tarde demais")
    assert s.obter(j, "t")["estado"] == "CONCLUIDO" and s.obter(j, "t")["resultado"] == {"a": 1}
    with pytest.raises(ValueError):
        s.atualizar(j, "INVENTADO")


# ----------------------------------------------------------------------------- lote
def test_lote_processa_cada_arquivo_pelo_pipeline(client, tmp_path):
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    app = client.app
    definir_contexto(Contexto(
        audit=app.state.audit.worm, dispatcher=app.state.dispatcher, lgpd=app.state.lgpd, status=app.state.rpa_status,
        config_fgts=ConfigPortalFGTS(), pasta_de_trabalho=tmp_path / "rpa", chave_privada_rpa=None, chave_hash="x" * 20,
    ))
    try:
        h = entrar(client)
        arquivos = [("arquivos", ("a.txt", HOLERITE.encode())), ("arquivos", ("b.txt", b"papo furado sem nada")), ("arquivos", ("c.txt", b"   "))]
        r = client.post("/api/v1/documentos/lote", files=arquivos, headers=h)
        assert r.status_code == 202 and r.json()["arquivos"] == 3
        job = client.get(f"/api/v1/rpa/jobs/{r.json()['job_id']}", headers=h).json()
        assert job["estado"] == "CONCLUIDO"
        assert job["resultado"]["resumo"] == {"arquivado": 1, "falhou": 1, "invalido": 1, "recusado": 0}
        assert job["resultado"]["itens"][0]["tipo"] == "HOLERITE"
    finally:
        definir_contexto(None)
        celery_app.conf.task_always_eager = False


def test_lote_recusa_nomes_com_caminho_e_limites(client, tmp_path):
    from contabil_agente.tarefas.documentos import processar_lote

    celery_app.conf.task_always_eager = True
    app = client.app
    definir_contexto(Contexto(
        audit=app.state.audit.worm, dispatcher=app.state.dispatcher, lgpd=app.state.lgpd, status=app.state.rpa_status,
        config_fgts=ConfigPortalFGTS(), pasta_de_trabalho=tmp_path, chave_privada_rpa=None, chave_hash="x" * 20,
    ))
    try:
        job = app.state.rpa_status.criar("empresa_a", "u", "lote_documentos")
        (tmp_path / "segredo.txt").write_text("HOLERITE")
        pasta = tmp_path / "entrada"
        pasta.mkdir()
        r = processar_lote.apply(args=[job, "empresa_a", "u", str(pasta), ["../segredo.txt", "..\\segredo.txt", "/etc/passwd"]]).get()
        assert r["resumo"]["recusado"] == 3
        h = entrar(client)
        assert client.post("/api/v1/documentos/lote", files=[], headers=h).status_code == 422
    finally:
        definir_contexto(None)
        celery_app.conf.task_always_eager = False


# ------------------------------------------------------------------------------- CLI
def test_cli_gera_chaves_do_rpa_e_cria_usuario(tmp_path, monkeypatch, capsys):
    from agente_v2 import cli

    assert cli.main(["gerar-chaves-rpa", "--saida", str(tmp_path / "k")]) == 0
    pub = json.loads((tmp_path / "k" / "rpa_publica.json").read_text())
    priv = json.loads((tmp_path / "k" / "rpa_privada.json").read_text())
    assert pqc.decifrar_hibrido(priv, pqc.cifrar_hibrido(pub, b"ok")) == b"ok"
    assert "RPA_PQC_PUBLIC_KEY=" in capsys.readouterr().out

    monkeypatch.setenv("JWT_SECRET", "s" * 40)
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("NOVA_SENHA", "Senha-Forte-123")
    assert cli.main(["criar-usuario", "--usuario", "ana", "--tenant", "t", "--papeis", "accountant"]) == 0
    monkeypatch.setenv("NOVA_SENHA", "fraca")
    assert cli.main(["criar-usuario", "--usuario", "bia", "--tenant", "t", "--papeis", "accountant"]) == 1
    assert cli.main(["gerar-segredo"]) == 0


def test_cli_verifica_a_auditoria(tmp_path, monkeypatch, capsys):
    from agente_v2 import cli
    from contabil_agente.security.worm_audit import WormAudit

    monkeypatch.setenv("AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("AUDIT_HMAC_KEY", "k" * 40)
    worm = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    worm.append("x", {}, tenant="t1")
    assert cli.main(["verificar-auditoria", "--tenant", "t1"]) == 0
    arq = worm._caminho("t1")
    arq.write_text(arq.read_text(encoding="utf-8").replace('"evento":"x"', '"evento":"y"'), encoding="utf-8")
    assert cli.main(["verificar-auditoria"]) == 1


def test_exclusao_do_titular_tambem_apaga_os_trabalhos_do_rpa(rpa):
    h = consentir(rpa)
    job_id = rpa.post("/api/v1/rpa/fgts", json={"cpf": CPF}, headers=h).json()["job_id"]
    assert rpa.get(f"/api/v1/rpa/jobs/{job_id}", headers=h).status_code == 200
    r = rpa.request("DELETE", "/api/v1/lgpd/titular", json={"documento": CPF}, headers=entrar(rpa, "admin"))
    assert r.status_code == 200 and r.json()["trabalhos_rpa"] == 1
    assert rpa.get(f"/api/v1/rpa/jobs/{job_id}", headers=h).status_code == 404
