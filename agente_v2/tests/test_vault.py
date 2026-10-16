"""Vault: o hvac real conversando com um servidor HTTP que implementa o protocolo KV v2 e AppRole."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agente_v2.vault_client import SegredoIndisponivel, VaultClient, carregar_segredos


class FakeVault:
    """Servidor mínimo: /v1/auth/approle/login, /v1/secret/data/<path>, /v1/sys/health."""

    def __init__(self):
        self.segredos = {"agente": {"jwt_secret": "j" * 40, "audit_hmac_key": "a" * 40, "gemini_api_key": "g-123"},
                         "certs": {"a1_cert": "-----BEGIN CERTIFICATE-----x", "a1_key": "-----BEGIN PRIVATE KEY-----y"}}
        self.token_valido = {"s.token-fixo", "s.approle-1"}
        self.logins, self.leituras, self.selado, self.lease = 0, 0, False, 3600
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, status, corpo):
                dados = json.dumps(corpo).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def do_GET(self):
                if self.path.startswith("/v1/sys/health"):
                    return self._json(503 if fake.selado else 200, {"initialized": True, "sealed": fake.selado})
                if self.headers.get("X-Vault-Token") not in fake.token_valido:
                    return self._json(403, {"errors": ["permission denied"]})
                if self.path.startswith("/v1/secret/data/"):
                    nome = self.path[len("/v1/secret/data/"):].split("?")[0]
                    fake.leituras += 1
                    if nome not in fake.segredos:
                        return self._json(404, {"errors": []})
                    return self._json(200, {"data": {"data": fake.segredos[nome], "metadata": {"version": 1}}})
                self._json(404, {"errors": ["rota"]})

            def do_POST(self):
                tam = int(self.headers.get("Content-Length") or 0)
                corpo = json.loads(self.rfile.read(tam) or b"{}")
                if self.path == "/v1/auth/approle/login":
                    if corpo.get("role_id") == "role-ok" and corpo.get("secret_id") == "secret-ok":
                        fake.logins += 1
                        return self._json(200, {"auth": {"client_token": "s.approle-1", "lease_duration": fake.lease, "renewable": True}})
                    return self._json(400, {"errors": ["invalid role or secret ID"]})
                self._json(404, {"errors": []})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def parar(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture()
def vault_falso():
    f = FakeVault()
    yield f
    f.parar()


def test_le_segredo_com_token(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo")
    assert v.get_secret("agente", "jwt_secret") == "j" * 40
    assert v.ler("agente")["gemini_api_key"] == "g-123"


def test_login_approle_obtem_o_token_e_le(vault_falso):
    v = VaultClient(url=vault_falso.url, role_id="role-ok", secret_id="secret-ok")
    assert vault_falso.logins == 1 and v.get_secret("agente", "audit_hmac_key") == "a" * 40


def test_approle_com_credencial_errada_falha(vault_falso):
    with pytest.raises(SegredoIndisponivel):
        VaultClient(url=vault_falso.url, role_id="role-ok", secret_id="errado")


def test_token_invalido_vira_sem_permissao(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.invalido")
    with pytest.raises(SegredoIndisponivel, match="permiss"):
        v.ler("agente")


def test_caminho_inexistente_levanta_e_nao_devolve_none(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo")
    with pytest.raises(SegredoIndisponivel, match="inexistente"):
        v.ler("nao_existe")


def test_vault_fora_do_ar_levanta_sem_fallback_silencioso(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo")
    vault_falso.parar()
    with pytest.raises(SegredoIndisponivel, match="indispon"):
        v.ler("agente")


def test_cache_evita_nova_leitura_e_expira(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo", cache_ttl=0.2)
    v.ler("agente")
    v.ler("agente")
    assert vault_falso.leituras == 1
    import time

    time.sleep(0.3)
    v.ler("agente")
    assert vault_falso.leituras == 2
    v.limpar_cache()
    v.ler("agente")
    assert vault_falso.leituras == 3


def test_certificado_e_chave_privada(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo")
    assert v.get_certificate("certs", "a1_cert").startswith("-----BEGIN CERTIFICATE")
    assert v.get_private_key("certs", "a1_key").startswith("-----BEGIN PRIVATE KEY")
    with pytest.raises(SegredoIndisponivel):
        v.get_private_key("certs", "nao_tem")


def test_saude_do_vault(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo")
    assert v.saudavel() is True
    vault_falso.selado = True
    assert v.saudavel() is False


def test_do_ambiente(vault_falso):
    assert VaultClient.do_ambiente({}) is None
    v = VaultClient.do_ambiente({"VAULT_ADDR": vault_falso.url, "VAULT_TOKEN": "s.token-fixo"})
    assert v.get_secret("agente", "jwt_secret")
    with pytest.raises(SegredoIndisponivel):
        VaultClient.do_ambiente({"VAULT_ADDR": vault_falso.url})  # sem token nem approle


def test_carregar_segredos_o_vault_manda_sobre_o_ambiente(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo")
    env = carregar_segredos(v, {"JWT_SECRET": "do-ambiente-que-sera-ignorado-0000000000", "OUTRA": "x"})
    assert env["JWT_SECRET"] == "j" * 40 and env["AUDIT_HMAC_KEY"] == "a" * 40 and env["GEMINI_API_KEY"] == "g-123"
    assert env["OUTRA"] == "x" and "DEEPSEEK_API_KEY" not in env


def test_carregar_segredos_sem_vault_usa_so_o_ambiente():
    assert carregar_segredos(None, {"JWT_SECRET": "x" * 40}) == {"JWT_SECRET": "x" * 40}


def test_carregar_segredos_com_vault_configurado_e_quebrado_nao_cai_no_ambiente(vault_falso):
    v = VaultClient(url=vault_falso.url, token="s.token-fixo")
    vault_falso.parar()
    with pytest.raises(SegredoIndisponivel):
        carregar_segredos(v, {"JWT_SECRET": "x" * 40})


def test_backend_em_memoria_para_desenvolvimento():
    v = VaultClient.em_memoria({"agente": {"jwt_secret": "m" * 40}})
    assert v.get_secret("agente", "jwt_secret") == "m" * 40 and v.saudavel()
    v.gravar("novo", {"a": "b"})
    assert v.get_secret("novo", "a") == "b"
    with pytest.raises(SegredoIndisponivel):
        v.ler("nada")


# ------------------------------------------------------- integração com a API
def test_api_sobe_com_os_segredos_do_vault_e_o_login_funciona(vault_falso, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agente_v2.main import create_app

    for k in ("JWT_SECRET", "AUDIT_HMAC_KEY", "AGENTE_ENV", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "ADMIN_USERNAME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VAULT_ADDR", vault_falso.url)
    monkeypatch.setenv("VAULT_TOKEN", "s.token-fixo")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    app = create_app()
    assert app.state.auth.settings.secret == "j" * 40
    assert app.state.audit.worm._chave == b"a" * 40
    assert app.state.dispatcher.revisor_llm is not None  # gemini_api_key veio do Vault
    app.state.auth.criar_usuario("maria", "Senha-Forte-123", "t", ["accountant"])
    c = TestClient(app)
    assert c.post("/token", data={"username": "maria", "password": "Senha-Forte-123"}).status_code == 200
    assert c.get("/ready").json()["vault"] is True


def test_api_nao_sobe_se_o_vault_esta_configurado_e_fora_do_ar(vault_falso, tmp_path, monkeypatch):
    from agente_v2.main import create_app

    monkeypatch.setenv("JWT_SECRET", "x" * 40)  # existir no ambiente não pode mascarar a falha do Vault
    monkeypatch.setenv("AUDIT_HMAC_KEY", "y" * 40)
    monkeypatch.setenv("VAULT_ADDR", vault_falso.url)
    monkeypatch.setenv("VAULT_TOKEN", "s.token-fixo")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    vault_falso.parar()
    with pytest.raises(SegredoIndisponivel):
        create_app()
