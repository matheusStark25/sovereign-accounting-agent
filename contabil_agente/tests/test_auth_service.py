"""Autenticação: sem segredo padrão, senha com bcrypt, JWT assinado, bloqueio e revogação."""

import time

import jwt
import pytest

from contabil_agente.security.auth import (
    AuthConfigError,
    AuthError,
    AuthLockedError,
    AuthService,
    AuthSettings,
)
from contabil_agente.security.rbac_manager import Permission, RBACManager, SecurityError

SEGREDO = "x" * 40
SENHA = "Senha-Forte-123"


@pytest.fixture()
def auth(tmp_path):
    settings = AuthSettings(secret=SEGREDO, db_path=str(tmp_path / "auth.db"))
    return AuthService(settings, rbac=RBACManager())


@pytest.fixture()
def contador(auth):
    return auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])


def test_sem_jwt_secret_em_producao_nao_sobe():
    with pytest.raises(AuthConfigError):
        AuthSettings.from_env({})


def test_segredo_curto_e_recusado():
    with pytest.raises(AuthConfigError):
        AuthSettings.from_env({"JWT_SECRET": "curto"})


def test_modo_dev_gera_segredo_temporario_diferente_a_cada_vez():
    a = AuthSettings.from_env({"AGENTE_ENV": "dev"})
    b = AuthSettings.from_env({"AGENTE_ENV": "dev"})
    assert len(a.secret) >= 32 and a.secret != b.secret


def test_login_certo_devolve_o_principal(auth, contador):
    p = auth.autenticar("maria", SENHA)
    assert p.user_id == contador.user_id and p.tenant_id == "empresa_a" and p.roles == {"accountant"}


def test_senha_errada_e_usuario_inexistente_dao_a_mesma_mensagem(auth, contador):
    with pytest.raises(AuthError) as e1:
        auth.autenticar("maria", "errada-errada-1A")
    with pytest.raises(AuthError) as e2:
        auth.autenticar("ninguem", SENHA)
    assert str(e1.value) == str(e2.value)


def test_senha_fraca_e_recusada(auth):
    for fraca in ("curta1A!", "tudominusculo", "SOMENTEMAIUSCULO", "1234567890"):
        with pytest.raises(ValueError):
            auth.criar_usuario("novo", fraca, "t", ["viewer"])


def test_senha_nao_fica_em_texto_no_banco(auth, contador):
    with auth._db() as con:
        guardado = con.execute("SELECT password_hash FROM users").fetchone()[0]
    assert SENHA not in guardado and guardado.startswith("$2")


def test_papel_invalido_e_usuario_duplicado(auth, contador):
    with pytest.raises(ValueError):
        auth.criar_usuario("outro", SENHA, "t", ["deus"])
    with pytest.raises(ValueError):
        auth.criar_usuario("MARIA", SENHA, "t", ["viewer"])


def test_cinco_erros_bloqueiam_a_conta_ate_com_a_senha_certa(auth, contador):
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.autenticar("maria", "errada-errada-1A")
    with pytest.raises(AuthLockedError):
        auth.autenticar("maria", SENHA)


def test_token_ida_e_volta(auth, contador):
    token = auth.emitir_token(contador)
    assert auth.verificar_token(token) == contador


def test_token_adulterado_ou_de_outro_segredo_e_recusado(auth, contador, tmp_path):
    token = auth.emitir_token(contador)
    with pytest.raises(AuthError):
        auth.verificar_token(token[:-3] + "abc")
    falso = jwt.encode({"sub": contador.user_id}, "y" * 40, algorithm="HS256")
    with pytest.raises(AuthError):
        auth.verificar_token(falso)


def test_token_sem_assinatura_alg_none_e_recusado(auth, contador):
    sem_assinatura = jwt.encode({"sub": contador.user_id, "roles": ["super_admin"]}, key=None, algorithm="none")
    with pytest.raises(AuthError):
        auth.verificar_token(sem_assinatura)


def test_token_expirado_e_recusado(tmp_path):
    settings = AuthSettings(secret=SEGREDO, db_path=str(tmp_path / "a.db"), access_minutes=1)
    servico = AuthService(settings, rbac=RBACManager())
    p = servico.criar_usuario("joao", SENHA, "t", ["viewer"])
    token = servico.emitir_token(p)
    claims = jwt.decode(token, SEGREDO, algorithms=["HS256"], audience="sovereign-accounting-api")
    claims["exp"] = int(time.time()) - 10
    velho = jwt.encode(claims, SEGREDO, algorithm="HS256")
    with pytest.raises(AuthError):
        servico.verificar_token(velho)


def test_logout_revoga_o_token(auth, contador):
    token = auth.emitir_token(contador)
    auth.revogar_token(token)
    with pytest.raises(AuthError):
        auth.verificar_token(token)


def test_usuario_desativado_perde_o_acesso_na_hora(auth, contador):
    token = auth.emitir_token(contador)
    auth.desativar_usuario("maria")
    with pytest.raises(AuthError):
        auth.verificar_token(token)


def test_papeis_no_token_nao_valem_so_o_banco(auth, contador):
    """Mesmo um token assinado dizendo super_admin não eleva o usuário: vale o que está no banco."""
    claims = jwt.decode(auth.emitir_token(contador), SEGREDO, algorithms=["HS256"], audience="sovereign-accounting-api")
    claims["roles"] = ["super_admin"]
    adulterado = jwt.encode(claims, SEGREDO, algorithm="HS256")
    assert auth.verificar_token(adulterado).roles == {"accountant"}


def test_autorizacao_por_papel(auth, contador):
    auth.autorizar(contador, Permission.PROCESS_PAYROLL)
    with pytest.raises(PermissionError):
        auth.autorizar(contador, Permission.MANAGE_USERS)


def test_visualizador_nao_processa_folha(auth):
    v = auth.criar_usuario("vera", SENHA, "empresa_a", ["viewer"])
    with pytest.raises(PermissionError):
        auth.autorizar(v, Permission.PROCESS_PAYROLL)


def test_isolamento_entre_tenants(auth, contador):
    with pytest.raises(SecurityError):
        auth.autorizar(contador, Permission.PROCESS_PAYROLL, tenant_do_recurso="empresa_b")
