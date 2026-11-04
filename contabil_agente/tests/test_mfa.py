"""Verificação em duas etapas: TOTP conferido contra os vetores das RFCs 4226 e 6238, segredo cifrado e login com o código."""

import sqlite3
import time

import pytest

from contabil_agente.security import mfa
from contabil_agente.security.auth import AuthError, AuthLockedError, AuthMFANecessario, AuthService, AuthSettings
from contabil_agente.security.rbac_manager import RBACManager

SENHA = "Senha-Forte-123"
RFC_SHA1 = b"12345678901234567890"
RFC_SHA256 = b"12345678901234567890123456789012"
RFC_SHA512 = b"1234567890123456789012345678901234567890123456789012345678901234"


# ------------------------------------------------------------------ o algoritmo
def test_hotp_bate_com_os_vetores_da_rfc_4226():
    esperados = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583", "399871", "520489"]
    assert [mfa.hotp(RFC_SHA1, contador) for contador in range(10)] == esperados


@pytest.mark.parametrize("instante,sha1,sha256,sha512", [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111111, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
])
def test_totp_bate_com_os_vetores_da_rfc_6238(instante, sha1, sha256, sha512):
    contador = mfa.passo(instante)
    assert mfa.hotp(RFC_SHA1, contador, 8, "sha1") == sha1
    assert mfa.hotp(RFC_SHA256, contador, 8, "sha256") == sha256
    assert mfa.hotp(RFC_SHA512, contador, 8, "sha512") == sha512


def test_segredo_novo_e_o_codigo_do_momento_com_um_passo_de_tolerancia():
    s, agora = mfa.gerar_segredo(), 1_800_000_000
    assert len(mfa.chave_do_segredo(s)) == 20  # 160 bits
    assert mfa.conferir_totp(s, mfa.totp(s, agora), agora) == mfa.passo(agora)
    assert mfa.conferir_totp(s, mfa.totp(s, agora - 30), agora) == mfa.passo(agora) - 1  # celular 30 s atrasado
    assert mfa.conferir_totp(s, mfa.totp(s, agora - 90), agora) is None  # fora da janela
    assert mfa.conferir_totp(s, "12345", agora) is None and mfa.conferir_totp(s, "abcdef", agora) is None


def test_codigo_ja_usado_nao_vale_de_novo():
    s, agora = mfa.gerar_segredo(), 1_800_000_000
    p = mfa.conferir_totp(s, mfa.totp(s, agora), agora)
    assert mfa.conferir_totp(s, mfa.totp(s, agora), agora, ultimo_passo=p) is None
    assert mfa.conferir_totp(s, mfa.totp(s, agora + 30), agora, ultimo_passo=p) == p + 1


def test_uri_e_qr_code_para_o_aplicativo():
    s = mfa.gerar_segredo()
    uri = mfa.uri_de_configuracao(s, "maria@empresa")
    assert uri.startswith("otpauth://totp/Sovereign%20Accounting%20Agent:maria%40empresa?")
    assert f"secret={s}" in uri and "issuer=Sovereign%20Accounting%20Agent" in uri and "digits=6" in uri
    assert mfa.qr_code(uri).startswith("data:image/svg+xml")


def test_codigos_de_recuperacao_unicos_e_sem_caracteres_ambiguos():
    codigos = mfa.gerar_codigos_de_recuperacao()
    assert len(codigos) == 10 == len(set(codigos))
    assert all(len(mfa.normalizar_recuperacao(c)) == 10 and not set(c) & set("01ilo") for c in codigos)
    assert mfa.normalizar_recuperacao(" K7M2P-X9QRT ") == "k7m2px9qrt"


def test_segredo_cifrado_so_abre_com_a_mesma_chave_e_o_mesmo_usuario():
    c = mfa.CifraDeSegredos("k" * 40)
    cifrado = c.cifrar("SEGREDO", "usr_1")
    assert "SEGREDO" not in cifrado and c.decifrar(cifrado, "usr_1") == "SEGREDO"
    with pytest.raises(mfa.SegredoInvalido):
        c.decifrar(cifrado, "usr_2")  # copiado para a linha de outro usuário
    with pytest.raises(mfa.SegredoInvalido):
        mfa.CifraDeSegredos("x" * 40).decifrar(cifrado, "usr_1")  # chave trocada
    with pytest.raises(ValueError):
        mfa.CifraDeSegredos("curta")


# ------------------------------------------------------------------ o login
def novo_auth(tmp_path):
    return AuthService(AuthSettings(secret="s" * 40, db_path=str(tmp_path / "auth.db")), rbac=RBACManager())


def ativar(auth, principal):
    dados = auth.iniciar_mfa(principal)
    return dados["segredo"], auth.ativar_mfa(principal, SENHA, mfa.totp(dados["segredo"]))


def proximo_codigo(segredo):
    """O código do passo seguinte: o do passo atual já foi gasto na ativação."""
    return mfa.totp(segredo, time.time() + 30)


def test_login_pede_o_codigo_so_depois_de_ativar(tmp_path):
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    assert auth.autenticar("maria", SENHA) == p
    segredo, codigos = ativar(auth, p)
    assert len(codigos) == 10 and auth.estado_mfa(p.user_id) == {"ativo": True, "codigos_de_recuperacao_restantes": 10}
    with pytest.raises(AuthMFANecessario):
        auth.autenticar("maria", SENHA)
    codigo = proximo_codigo(segredo)
    assert auth.autenticar("maria", SENHA, codigo).user_id == p.user_id
    with pytest.raises(AuthError) as repetido:
        auth.autenticar("maria", SENHA, codigo)  # o mesmo código não entra duas vezes
    assert type(repetido.value) is AuthError


def test_senha_errada_nunca_revela_que_a_conta_tem_duas_etapas(tmp_path):
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    ativar(auth, p)
    with pytest.raises(AuthError) as e:
        auth.autenticar("maria", "Senha-Errada-999")
    assert type(e.value) is AuthError and "senha" in str(e.value).lower()


def test_codigo_errado_conta_como_tentativa_e_bloqueia_a_conta(tmp_path):
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    ativar(auth, p)
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.autenticar("maria", SENHA, "000000")
    with pytest.raises(AuthLockedError):
        auth.autenticar("maria", SENHA, "000000")


def test_codigo_de_recuperacao_entra_uma_vez_so(tmp_path):
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    _, codigos = ativar(auth, p)
    assert auth.autenticar("maria", SENHA, codigos[0].upper()).user_id == p.user_id  # maiúsculas e hífen não importam
    with pytest.raises(AuthError):
        auth.autenticar("maria", SENHA, codigos[0])
    assert auth.estado_mfa(p.user_id)["codigos_de_recuperacao_restantes"] == 9


def test_ativar_e_desativar_exigem_senha_e_codigo_certos(tmp_path):
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    with pytest.raises(ValueError):
        auth.ativar_mfa(p, SENHA, "123456")  # sem gerar o QR code antes
    dados = auth.iniciar_mfa(p)
    with pytest.raises(AuthError):
        auth.ativar_mfa(p, "Senha-Errada-999", mfa.totp(dados["segredo"]))
    with pytest.raises(AuthError):
        auth.ativar_mfa(p, SENHA, "000000")
    assert auth.estado_mfa(p.user_id)["ativo"] is False
    auth.ativar_mfa(p, SENHA, mfa.totp(dados["segredo"]))
    with pytest.raises(ValueError):
        auth.iniciar_mfa(p)  # já está ativa
    with pytest.raises(AuthError):
        auth.desativar_mfa(p, SENHA, "000000")
    auth.desativar_mfa(p, SENHA, proximo_codigo(dados["segredo"]))
    assert auth.estado_mfa(p.user_id)["ativo"] is False and auth.autenticar("maria", SENHA).user_id == p.user_id


def test_segredo_e_codigos_nunca_ficam_em_claro_no_banco(tmp_path):
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    segredo, codigos = ativar(auth, p)
    con = sqlite3.connect(tmp_path / "auth.db")
    cifrado, recuperacao = con.execute("SELECT mfa_secret, mfa_recovery FROM users").fetchone()
    con.close()
    assert segredo not in cifrado and not any(c in recuperacao or mfa.normalizar_recuperacao(c) in recuperacao for c in codigos)


def test_banco_criado_antes_das_duas_etapas_ganha_as_colunas_novas(tmp_path):
    con = sqlite3.connect(tmp_path / "auth.db")
    con.executescript(
        "CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, "
        "tenant_id TEXT NOT NULL, roles TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, failed_attempts INTEGER NOT NULL DEFAULT 0, "
        "locked_until REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL);"
    )
    con.close()
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    assert auth.estado_mfa(p.user_id)["ativo"] is False
    ativar(auth, p)
    assert auth.estado_mfa(p.user_id)["ativo"] is True


def test_administrador_redefine_quando_a_pessoa_perde_o_celular(tmp_path):
    auth = novo_auth(tmp_path)
    p = auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    ativar(auth, p)
    assert auth.redefinir_mfa("maria") is True and auth.redefinir_mfa("ninguem") is False
    assert auth.autenticar("maria", SENHA).user_id == p.user_id


def test_chave_propria_da_verificacao_em_duas_etapas_pelo_ambiente():
    env = {"JWT_SECRET": "j" * 40, "AUTH_DB_PATH": ":memory:"}
    assert AuthSettings.from_env(env).mfa_key is None
    assert AuthSettings.from_env({**env, "MFA_ENCRYPTION_KEY": "m" * 40}).mfa_key == "m" * 40
    from contabil_agente.security.auth import AuthConfigError

    with pytest.raises(AuthConfigError):
        AuthSettings.from_env({**env, "MFA_ENCRYPTION_KEY": "curta"})
