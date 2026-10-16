"""API FastAPI de ponta a ponta: login, RBAC, chat com cálculo real e isolamento entre usuários."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from agente_v2.main import create_app
from contabil_agente.chat import ChatEngine, ChatStore
from contabil_agente.chat.llm import LLMIndisponivel
from contabil_agente.security.audit_trail_manager import AuditTrailManager
from contabil_agente.security.auth import AuthService, AuthSettings
from contabil_agente.security.worm_audit import WormAudit
from contabil_agente.security.rbac_manager import RBACManager

SENHA = "Senha-Forte-123"
HOJE = date(2026, 9, 20)


class LLMFalso:
    def __init__(self):
        self.recebido = []

    def __call__(self, mensagens):
        self.recebido.append(mensagens)
        return "Resposta de teste do LLM."


def nova_auditoria(tmp_path):
    return AuditTrailManager(worm=WormAudit(tmp_path / "audit", "a" * 40, fsync=False))


def novo_auth(tmp_path, nome="auth.db"):
    return AuthService(AuthSettings(secret="s" * 40, db_path=str(tmp_path / nome)), rbac=RBACManager())


@pytest.fixture()
def llm():
    return LLMFalso()


@pytest.fixture()
def client(tmp_path, llm):
    auth = novo_auth(tmp_path)
    auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    auth.criar_usuario("joao", SENHA, "empresa_b", ["accountant"])
    auth.criar_usuario("vera", SENHA, "empresa_a", ["viewer"])
    auth.criar_usuario("admin", SENHA, "empresa_a", ["tenant_admin"])
    app = create_app(
        auth=auth,
        engine=ChatEngine(llm=llm, hoje=HOJE),
        store=ChatStore(str(tmp_path / "chat.db")),
        audit=nova_auditoria(tmp_path),
    )
    return TestClient(app)


def entrar(client, usuario="maria", senha=SENHA):
    r = client.post("/token", data={"username": usuario, "password": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health_e_ready_sem_login(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200


def test_nao_existe_usuario_padrao(client):
    for usuario, senha in (("alice", "secret"), ("admin", "admin"), ("admin", "password")):
        assert client.post("/token", data={"username": usuario, "password": senha}).status_code == 401


def test_login_e_me(client):
    r = client.get("/users/me", headers=entrar(client))
    assert r.status_code == 200
    assert r.json()["username"] == "maria" and r.json()["tenant_id"] == "empresa_a"


def test_rotas_protegidas_exigem_token(client):
    assert client.post("/api/chat", json={"message": "oi"}).status_code == 401
    assert client.get("/users/me").status_code == 401
    assert client.post("/api/v1/calculo/inss", json={}).status_code == 401
    assert client.get("/api/chat/x").status_code == 401


def test_cabecalhos_de_identidade_do_cliente_sao_ignorados(client):
    r = client.post(
        "/api/chat",
        json={"message": "oi"},
        headers={"X-User-ID": "x", "X-Tenant-ID": "empresa_a", "X-User-Roles": "super_admin"},
    )
    assert r.status_code == 401


def test_token_invalido_e_recusado(client):
    assert client.get("/users/me", headers={"Authorization": "Bearer lixo"}).status_code == 401


def test_cinco_erros_bloqueiam_a_conta(client):
    for _ in range(5):
        assert client.post("/token", data={"username": "maria", "password": "errada-Errada-1"}).status_code == 401
    assert client.post("/token", data={"username": "maria", "password": SENHA}).status_code == 423


def test_logout_revoga_o_token(client):
    h = entrar(client)
    assert client.post("/logout", headers=h).status_code == 204
    assert client.get("/users/me", headers=h).status_code == 401


def test_visualizador_nao_usa_chat_nem_calculo(client):
    h = entrar(client, "vera")
    assert client.post("/api/chat", json={"message": "oi"}, headers=h).status_code == 403
    assert client.post("/api/v1/calculo/inss", json={"salario": 3000}, headers=h).status_code == 403


def test_chat_calcula_com_o_motor_real_em_varias_mensagens(client):
    h = entrar(client)
    r1 = client.post("/api/chat", json={"message": "quero calcular INSS"}, headers=h).json()
    assert "salário" in r1["response"].lower()
    sid = r1["session_id"]
    r2 = client.post("/api/chat", json={"message": "salário de R$ 3.000,00", "session_id": sid}, headers=h).json()
    assert r2["session_id"] == sid
    assert r2["dados_calculados"]["inss"] == 248.60
    assert "248,60" in r2["response"]


def test_chat_conversa_geral_vai_pro_llm_com_pii_mascarado(client, llm):
    h = entrar(client)
    r = client.post("/api/chat", json={"message": "o CPF 123.456.789-09 tem pendência? me explique o DARF"}, headers=h)
    assert r.json()["response"] == "Resposta de teste do LLM."
    enviado = " ".join(m["content"] for m in llm.recebido[0])
    assert "123.456.789-09" not in enviado and "***CPF***" in enviado


def test_chat_sem_llm_responde_o_que_sabe_fazer(tmp_path):
    auth = novo_auth(tmp_path)
    auth.criar_usuario("maria", SENHA, "t", ["accountant"])
    c = TestClient(create_app(auth=auth, engine=ChatEngine(llm=None), store=ChatStore(str(tmp_path / "c.db")), audit=nova_auditoria(tmp_path)))
    r = c.post("/api/chat", json={"message": "bom dia"}, headers=entrar(c))
    assert "rescisão" in r.json()["response"].lower()


def test_llm_fora_do_ar_nao_derruba_o_chat(tmp_path):
    def quebrado(_):
        raise LLMIndisponivel("fora")

    auth = novo_auth(tmp_path)
    auth.criar_usuario("maria", SENHA, "t", ["accountant"])
    c = TestClient(create_app(auth=auth, engine=ChatEngine(llm=quebrado), store=ChatStore(str(tmp_path / "c.db")), audit=nova_auditoria(tmp_path)))
    r = c.post("/api/chat", json={"message": "explique o DARF"}, headers=entrar(c))
    assert r.status_code == 200 and "Não consegui falar com a IA" in r.json()["response"]


def test_usuario_nao_le_conversa_de_outro(client):
    sid = client.post("/api/chat", json={"message": "oi"}, headers=entrar(client, "maria")).json()["session_id"]
    assert client.get(f"/api/chat/{sid}", headers=entrar(client, "maria")).status_code == 200
    assert client.get(f"/api/chat/{sid}", headers=entrar(client, "joao")).status_code == 404
    assert client.post("/api/chat", json={"message": "oi", "session_id": sid}, headers=entrar(client, "joao")).status_code == 404


def test_mensagem_vazia_ou_gigante(client):
    h = entrar(client)
    assert client.post("/api/chat", json={"message": ""}, headers=h).status_code == 422
    assert client.post("/api/chat", json={"message": "a" * 4001}, headers=h).status_code == 422


def test_calculo_rest_rescisao(client):
    corpo = {
        "tipo_rescisao": "sem_justa_causa",
        "salario": 3000,
        "data_admissao": "10/03/2023",
        "data_demissao": "15/09/2026",
        "aviso_previo": "indenizado",
        "saldo_fgts": 12000,
        "competencia": "2026-09-01",
    }
    r = client.post("/api/v1/calculo/rescisao", json=corpo, headers=entrar(client))
    assert r.status_code == 200
    assert r.json()["resultado"]["total_liquido"] == 10253.48


def test_calculo_rest_faltando_dado_e_tipo_desconhecido(client):
    h = entrar(client)
    r = client.post("/api/v1/calculo/ferias", json={}, headers=h)
    assert r.status_code == 422 and r.json()["status"] == "faltam_dados"
    assert client.post("/api/v1/calculo/astrologia", json={}, headers=h).status_code == 404


def test_criar_usuario_respeita_tenant_e_papeis(client):
    admin = entrar(client, "admin")
    ok = client.post("/users", json={"username": "novo.user", "password": SENHA, "roles": ["viewer"]}, headers=admin)
    assert ok.status_code == 201 and ok.json()["tenant_id"] == "empresa_a"
    outro_tenant = client.post(
        "/users", json={"username": "x.user", "password": SENHA, "roles": ["viewer"], "tenant_id": "empresa_b"}, headers=admin
    )
    assert outro_tenant.status_code == 403
    escalada = client.post("/users", json={"username": "y.user", "password": SENHA, "roles": ["super_admin"]}, headers=admin)
    assert escalada.status_code == 403
    contador = entrar(client, "maria")
    assert client.post("/users", json={"username": "z.user", "password": SENHA, "roles": ["viewer"]}, headers=contador).status_code == 403


def test_cabecalhos_de_seguranca(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_corpo_enorme_e_recusado(client):
    r = client.post("/token", content=b"x" * 1_100_000, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_app_sem_jwt_secret_falha_com_mensagem(monkeypatch):
    import agente_v2.main as m

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("AGENTE_ENV", raising=False)
    monkeypatch.setattr(m, "_app", None)
    with pytest.raises(Exception) as exc:
        m.app
    assert "JWT_SECRET" in str(exc.value)


def test_pdf_do_calculo_via_rest(client):
    corpo = {
        "dados": {"salario": 6000, "competencia": "2026-09-01"},
        "contexto": {"empresa": "Empresa Teste", "nome_funcionario": "Fulano", "ignorado": "x"},
    }
    r = client.post("/api/v1/calculo/folha/pdf", json=corpo, headers=entrar(client))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and len(r.headers["x-calculo-sha256"]) == 64


def test_pdf_com_dados_faltando_nao_gera_documento_vazio(client):
    r = client.post("/api/v1/calculo/ferias/pdf", json={"dados": {}}, headers=entrar(client))
    assert r.status_code == 422 and r.json()["status"] == "faltam_dados"


def test_pdf_do_ultimo_calculo_da_conversa(client):
    h = entrar(client)
    r1 = client.post("/api/chat", json={"message": "calcular INSS de um salário de R$ 5.000,00"}, headers=h).json()
    sid = r1["session_id"]
    pdf = client.get(f"/api/chat/{sid}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    # conversa sem cálculo concluído
    sem = client.post("/api/chat", json={"message": "oi"}, headers=h).json()["session_id"]
    assert client.get(f"/api/chat/{sem}/pdf", headers=h).status_code == 404
    # outro usuário não baixa
    assert client.get(f"/api/chat/{sid}/pdf", headers=entrar(client, "joao")).status_code == 404


# ----------------------------------------------------------------- auditoria WORM
def test_login_chat_e_calculo_geram_trilha_encadeada_sem_conteudo(client, tmp_path):
    h = entrar(client)
    client.post("/api/chat", json={"message": "meu segredo: CPF 529.982.247-25"}, headers=h)
    client.post("/api/v1/calculo/inss", json={"salario": 3000}, headers=h)
    worm = client.app.state.audit.worm
    v = worm.verificar("empresa_a")
    assert v.ok and v.entradas >= 3
    texto = worm._caminho("empresa_a").read_text(encoding="utf-8")
    assert "segredo" not in texto and "529.982.247-25" not in texto
    assert '"evento":"login"' in texto


def test_falha_de_login_vai_para_a_trilha_do_sistema(client):
    client.post("/token", data={"username": "maria", "password": "errada-Errada-1"})
    worm = client.app.state.audit.worm
    assert worm.verificar("SYSTEM").entradas == 1


def test_sem_trilha_a_operacao_nao_acontece(client, monkeypatch):
    h = entrar(client)
    audit = client.app.state.audit

    def quebrada(*a, **k):
        from contabil_agente.security.worm_audit import AuditoriaError

        raise AuditoriaError("disco cheio")

    monkeypatch.setattr(audit, "log", quebrada)
    r = client.post("/api/v1/calculo/inss", json={"salario": 3000}, headers=h)
    assert r.status_code == 503 and "auditoria" in r.json()["detail"].lower()


def test_adulterar_a_trilha_e_detectado_pela_verificacao(client):
    h = entrar(client)
    client.post("/api/v1/calculo/inss", json={"salario": 3000}, headers=h)
    client.post("/api/v1/calculo/inss", json={"salario": 4000}, headers=h)
    worm = client.app.state.audit.worm
    arq = worm._caminho("empresa_a")
    linhas = arq.read_text(encoding="utf-8").splitlines()
    del linhas[1]
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    assert not worm.verificar("empresa_a").ok
