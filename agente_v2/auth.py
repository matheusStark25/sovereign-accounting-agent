"""Dependências FastAPI de autenticação e autorização (implementação em ``contabil_agente.middleware.auth``)."""

from contabil_agente.middleware.auth import exigir, get_auth, token_da_requisicao, usuario_atual  # noqa: F401
