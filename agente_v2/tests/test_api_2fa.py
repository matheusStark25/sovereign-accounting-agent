"""Verificação em duas etapas pela API: configurar com QR code, entrar com o código, recuperação e auditoria."""

import time

from contabil_agente.security import mfa

from .test_api import SENHA, client, entrar, llm  # noqa: F401


def _ativar(client, h):  # noqa: F811
    dados = client.post("/users/me/2fa/iniciar", headers=h).json()
    r = client.post("/users/me/2fa/ativar", json={"senha": SENHA, "codigo": mfa.totp(dados["segredo"])}, headers=h)
    assert r.status_code == 200, r.text
    return dados, r.json()["codigos_de_recuperacao"]


def test_configura_pelo_qr_code_e_o_login_passa_a_pedir_o_codigo(client):  # noqa: F811
    h = entrar(client)
    assert client.get("/users/me/2fa", headers=h).json()["ativo"] is False
    dados = client.post("/users/me/2fa/iniciar", headers=h).json()
    assert dados["uri"].startswith("otpauth://totp/") and dados["qr_code"].startswith("data:image/svg+xml")
    r = client.post("/users/me/2fa/ativar", json={"senha": SENHA, "codigo": mfa.totp(dados["segredo"])}, headers=h)
    assert r.status_code == 200 and len(r.json()["codigos_de_recuperacao"]) == 10

    sem_codigo = client.post("/token", data={"username": "maria", "password": SENHA})
    assert sem_codigo.status_code == 401 and sem_codigo.headers["X-MFA-Required"] == "totp"
    errado = client.post("/token", data={"username": "maria", "password": SENHA, "codigo_2fa": "000000"})
    assert errado.status_code == 401 and "X-MFA-Required" not in errado.headers
    codigo = mfa.totp(dados["segredo"], time.time() + 30)
    certo = client.post("/token", data={"username": "maria", "password": SENHA, "codigo_2fa": codigo})
    assert certo.status_code == 200 and certo.json()["access_token"]
    assert client.get("/users/me/2fa", headers=h).json() == {"ativo": True, "codigos_de_recuperacao_restantes": 10}


def test_senha_errada_nao_revela_que_a_conta_tem_duas_etapas(client):  # noqa: F811
    _ativar(client, entrar(client))
    r = client.post("/token", data={"username": "maria", "password": "Senha-Errada-999"})
    assert r.status_code == 401 and "X-MFA-Required" not in r.headers


def test_senha_ou_codigo_errado_na_ativacao_da_400_e_nao_derruba_a_sessao(client):  # noqa: F811
    h = entrar(client)
    dados = client.post("/users/me/2fa/iniciar", headers=h).json()
    ruim = client.post("/users/me/2fa/ativar", json={"senha": "Senha-Errada-999", "codigo": mfa.totp(dados["segredo"])}, headers=h)
    assert ruim.status_code == 400
    assert client.post("/users/me/2fa/ativar", json={"senha": SENHA, "codigo": "000000"}, headers=h).status_code == 400
    assert client.get("/users/me", headers=h).status_code == 200
    assert client.get("/users/me/2fa", headers=h).json()["ativo"] is False


def test_ativar_de_novo_e_desativar_sem_estar_ativa_dao_409(client):  # noqa: F811
    h = entrar(client)
    assert client.post("/users/me/2fa/desativar", json={"senha": SENHA, "codigo": "123456"}, headers=h).status_code == 409
    _ativar(client, h)
    assert client.post("/users/me/2fa/iniciar", headers=h).status_code == 409


def test_desativar_com_codigo_de_recuperacao_e_a_trilha_registra(client):  # noqa: F811
    h = entrar(client)
    _, codigos = _ativar(client, h)
    r = client.post("/users/me/2fa/desativar", json={"senha": SENHA, "codigo": codigos[0]}, headers=h)
    assert r.status_code == 200 and r.json() == {"ativo": False}
    assert client.post("/token", data={"username": "maria", "password": SENHA}).status_code == 200
    eventos = [e["evento"] for e in client.app.state.audit.worm.ler("empresa_a")]
    assert "mfa_enabled" in eventos and "mfa_disabled" in eventos
    assert not any(c in str(e) for e in client.app.state.audit.worm.ler("empresa_a") for c in codigos)


def test_rotas_das_duas_etapas_exigem_login(client):  # noqa: F811
    assert client.get("/users/me/2fa").status_code == 401
    assert client.post("/users/me/2fa/iniciar").status_code == 401
    assert client.post("/users/me/2fa/ativar", json={"senha": SENHA, "codigo": "123456"}).status_code == 401
