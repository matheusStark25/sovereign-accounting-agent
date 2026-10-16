"""Autenticação real: usuários em SQLite, senha com bcrypt e token JWT assinado.

Regras que este módulo garante:

* Não existe usuário nem segredo padrão. ``JWT_SECRET`` é obrigatório (mínimo de 32
  caracteres). Só com ``AGENTE_ENV=dev`` é gerado um segredo temporário, que muda a
  cada início do processo.
* Quem é o usuário, o tenant e os papéis vêm do token assinado, nunca de cabeçalhos
  enviados pelo cliente.
* Cinco senhas erradas seguidas bloqueiam a conta por 15 minutos.
* Logout revoga o token (lista de ``jti`` revogados).
* A autorização usa o ``RBACManager`` (papéis, permissões e isolamento entre tenants).
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, FrozenSet, Iterator, Mapping, Optional

import bcrypt
import jwt

from .rbac_manager import Permission, RBACManager, Role

logger = logging.getLogger(__name__)

ISSUER = "sovereign-accounting-agent"
AUDIENCE = "sovereign-accounting-api"
MAX_TENTATIVAS = 5
BLOQUEIO_SEGUNDOS = 15 * 60
SENHA_MIN = 10
SENHA_MAX_BYTES = 72  # limite do bcrypt
PAPEIS_VALIDOS = {r.value for r in Role}
_USUARIO_RE = re.compile(r"^[a-zA-Z0-9_.@-]{3,64}$")
_TENANT_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


class AuthError(Exception):
    """Falha de autenticação (credencial ou token inválido)."""


class AuthConfigError(RuntimeError):
    """Configuração insegura ou ausente."""


class AuthLockedError(AuthError):
    """Conta temporariamente bloqueada por tentativas erradas."""


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    tenant_id: str
    roles: FrozenSet[str]

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "tenant_id": self.tenant_id,
            "roles": sorted(self.roles),
        }


@dataclass(frozen=True)
class AuthSettings:
    secret: str
    db_path: str
    access_minutes: int = 30

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AuthSettings":
        env = os.environ if env is None else env
        secret = env.get("JWT_SECRET", "")
        if not secret:
            if env.get("AGENTE_ENV", "production").lower() == "dev":
                secret = secrets.token_urlsafe(48)
                logger.warning("JWT_SECRET ausente: usando segredo temporário (AGENTE_ENV=dev).")
            else:
                raise AuthConfigError(
                    "Defina JWT_SECRET (mínimo 32 caracteres). Gere um com: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
        if len(secret) < 32:
            raise AuthConfigError("JWT_SECRET precisa ter pelo menos 32 caracteres.")
        base = Path(__file__).resolve().parent.parent / "data"
        db_path = env.get("AUTH_DB_PATH") or str(base / "auth.db")
        minutos = int(env.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        if not 1 <= minutos <= 24 * 60:
            raise AuthConfigError("ACCESS_TOKEN_EXPIRE_MINUTES deve ficar entre 1 e 1440.")
        return cls(secret=secret, db_path=db_path, access_minutes=minutos)


def validar_senha(senha: str) -> None:
    if not isinstance(senha, str) or len(senha) < SENHA_MIN:
        raise ValueError(f"A senha deve ter pelo menos {SENHA_MIN} caracteres.")
    if len(senha.encode("utf-8")) > SENHA_MAX_BYTES:
        raise ValueError(f"A senha deve ter no máximo {SENHA_MAX_BYTES} bytes.")
    classes = sum(bool(re.search(p, senha)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
    if classes < 3:
        raise ValueError("Use letras maiúsculas, minúsculas, números e/ou símbolos (pelo menos 3 tipos).")


def hash_senha(senha: str) -> str:
    validar_senha(senha)
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def conferir_senha(senha: str, hash_guardado: str) -> bool:
    bruta = senha.encode("utf-8")
    if len(bruta) > SENHA_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(bruta, hash_guardado.encode("ascii"))
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def _hash_falso() -> str:
    """Hash de senha aleatória: faz o login de usuário inexistente gastar o mesmo tempo."""
    return bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(rounds=12)).decode("ascii")


class AuthService:
    def __init__(self, settings: Optional[AuthSettings] = None, rbac: Optional[RBACManager] = None):
        self.settings = settings or AuthSettings.from_env()
        self._rbac = rbac or RBACManager()
        Path(self.settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._criar_tabelas()

    # ------------------------------------------------------------------ banco
    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.settings.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _criar_tabelas(self) -> None:
        with self._db() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    roles TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revoked_tokens (
                    jti TEXT PRIMARY KEY,
                    expires_at REAL NOT NULL
                );
                """
            )

    # --------------------------------------------------------------- usuários
    def contar_usuarios(self) -> int:
        with self._db() as con:
            return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def criar_usuario(self, username: str, senha: str, tenant_id: str, papeis: list[str]) -> Principal:
        if not _USUARIO_RE.match(username or ""):
            raise ValueError("Usuário inválido: use 3 a 64 caracteres (letras, números, _ . @ -).")
        if not _TENANT_RE.match(tenant_id or ""):
            raise ValueError("Tenant inválido: use até 64 caracteres (letras, números, _ . -).")
        papeis = sorted(set(papeis or []))
        desconhecidos = [p for p in papeis if p not in PAPEIS_VALIDOS]
        if not papeis or desconhecidos:
            raise ValueError(f"Papéis inválidos: {desconhecidos or papeis}. Válidos: {sorted(PAPEIS_VALIDOS)}.")
        user_id = f"usr_{uuid.uuid4().hex[:16]}"
        hash_ = hash_senha(senha)
        try:
            with self._db() as con:
                con.execute(
                    "INSERT INTO users (id, username, password_hash, tenant_id, roles, created_at) VALUES (?,?,?,?,?,?)",
                    (user_id, username, hash_, tenant_id, json.dumps(papeis), time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Já existe um usuário com esse nome.") from exc
        return Principal(user_id, username, tenant_id, frozenset(papeis))

    def desativar_usuario(self, username: str) -> None:
        with self._db() as con:
            con.execute("UPDATE users SET active = 0 WHERE username = ?", (username,))

    def _principal(self, linha: sqlite3.Row) -> Principal:
        return Principal(linha["id"], linha["username"], linha["tenant_id"], frozenset(json.loads(linha["roles"])))

    # ------------------------------------------------------------ autenticação
    def autenticar(self, username: str, senha: str) -> Principal:
        agora = time.time()
        with self._db() as con:
            linha = con.execute("SELECT * FROM users WHERE username = ?", (username or "",)).fetchone()
        if linha is None:
            conferir_senha(senha or "", _hash_falso())  # mesmo custo de tempo
            raise AuthError("Usuário ou senha inválidos.")
        if linha["locked_until"] > agora:
            raise AuthLockedError("Conta bloqueada por tentativas erradas. Tente novamente mais tarde.")
        if linha["active"] and conferir_senha(senha or "", linha["password_hash"]):
            with self._db() as con:
                con.execute("UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE id = ?", (linha["id"],))
            return self._principal(linha)
        # Falha: grava o erro numa transação própria e só depois levanta a exceção
        # (levantar dentro do ``with`` desfaria a gravação).
        with self._db() as con:
            con.execute("UPDATE users SET failed_attempts = failed_attempts + 1 WHERE id = ?", (linha["id"],))
            falhas = con.execute("SELECT failed_attempts FROM users WHERE id = ?", (linha["id"],)).fetchone()[0]
            if falhas >= MAX_TENTATIVAS:
                con.execute(
                    "UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                    (agora + BLOQUEIO_SEGUNDOS, linha["id"]),
                )
                logger.warning("Conta %s bloqueada após %d tentativas erradas.", linha["username"], MAX_TENTATIVAS)
        raise AuthError("Usuário ou senha inválidos.")

    # ------------------------------------------------------------------ tokens
    def emitir_token(self, principal: Principal) -> str:
        agora = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": principal.user_id,
            "usr": principal.username,
            "tenant": principal.tenant_id,
            "roles": sorted(principal.roles),
            "iat": agora,
            "exp": agora + self.settings.access_minutes * 60,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, self.settings.secret, algorithm="HS256")

    def verificar_token(self, token: str) -> Principal:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self.settings.secret,
                algorithms=["HS256"],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "sub", "jti", "tenant", "roles"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("Token inválido ou expirado.") from exc
        with self._db() as con:
            if con.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (claims["jti"],)).fetchone():
                raise AuthError("Token revogado.")
            linha = con.execute("SELECT * FROM users WHERE id = ?", (claims["sub"],)).fetchone()
        if linha is None or not linha["active"]:
            raise AuthError("Usuário inexistente ou desativado.")
        # papéis e tenant vêm do banco, então desativar ou rebaixar vale na hora
        return self._principal(linha)

    def revogar_token(self, token: str) -> None:
        try:
            claims = jwt.decode(
                token, self.settings.secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER
            )
        except jwt.PyJWTError:
            return
        with self._db() as con:
            con.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (time.time(),))
            con.execute(
                "INSERT OR IGNORE INTO revoked_tokens (jti, expires_at) VALUES (?, ?)",
                (claims["jti"], float(claims["exp"])),
            )

    # ------------------------------------------------------------ autorização
    def autorizar(
        self, principal: Principal, permissao: Permission, tenant_do_recurso: Optional[str] = None
    ) -> None:
        """Levanta ``PermissionError``/``SecurityError`` se o acesso não for permitido."""
        self._rbac.register_operator(
            operator_id=principal.user_id,
            tenant_id=principal.tenant_id,
            roles={Role(p) for p in principal.roles},
        )
        self._rbac.validate_access(
            principal.user_id, principal.tenant_id, permissao, resource_tenant_id=tenant_do_recurso
        )
