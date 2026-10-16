"""Dependências FastAPI de autenticação e autorização (sobre ``contabil_agente.security.auth``)."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from contabil_agente.security.auth import AuthError, AuthService, Principal
from contabil_agente.security.rbac_manager import Permission, SecurityError

_bearer = HTTPBearer(auto_error=False)
_NAO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Autenticação necessária.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


def token_da_requisicao(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if credenciais is None or credenciais.scheme.lower() != "bearer" or not credenciais.credentials:
        raise _NAO_AUTENTICADO
    return credenciais.credentials


def usuario_atual(
    token: str = Depends(token_da_requisicao), auth: AuthService = Depends(get_auth)
) -> Principal:
    try:
        return auth.verificar_token(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def exigir(permissao: Permission) -> Callable[..., Principal]:
    """Dependência que só deixa passar quem tem ``permissao`` (papéis vêm do banco, não do cliente)."""

    def dependencia(
        usuario: Principal = Depends(usuario_atual), auth: AuthService = Depends(get_auth)
    ) -> Principal:
        try:
            auth.autorizar(usuario, permissao)
        except (PermissionError, SecurityError) as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para esta operação.") from exc
        return usuario

    return dependencia
