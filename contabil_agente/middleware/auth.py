"""
Middleware de Autenticação Multi-Tenant
"""

import functools
import logging

from config_empresas import get_empresa_config, validate_api_key
from flask import g, jsonify, request

logger = logging.getLogger(__name__)


def require_api_key(f):
    """Decorator para exigir autenticação por API key"""

    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Pegar empresa_id da URL ou header
        empresa_id = kwargs.get("empresa_id") or request.headers.get("X-Empresa-ID")
        api_key = request.headers.get("X-API-Key")

        if not empresa_id:
            logger.warning("Request sem empresa_id")
            return (
                jsonify(
                    {"error": "Empresa ID não fornecido", "code": "MISSING_EMPRESA_ID"}
                ),
                400,
            )

        if not api_key:
            logger.warning(f"Request sem API key para empresa {empresa_id}")
            return (
                jsonify({"error": "API Key não fornecida", "code": "MISSING_API_KEY"}),
                401,
            )

        # Validar API key
        if not validate_api_key(empresa_id, api_key):
            logger.warning(f"API key inválida para empresa {empresa_id}")
            return (
                jsonify({"error": "API Key inválida", "code": "INVALID_API_KEY"}),
                403,
            )

        # Armazenar empresa_id e config no contexto
        try:
            g.empresa_id = empresa_id
            g.empresa_config = get_empresa_config(empresa_id)
            logger.info(f"Request autenticado para empresa: {g.empresa_config.nome}")
        except ValueError as e:
            logger.error(f"Erro ao carregar config da empresa: {e}")
            return jsonify({"error": str(e), "code": "INVALID_EMPRESA"}), 404

        return f(*args, **kwargs)

    return decorated_function


def get_current_empresa():
    """Retorna configuração da empresa atual do contexto"""
    return getattr(g, "empresa_config", None)


def get_current_empresa_id():
    """Retorna ID da empresa atual do contexto"""
    return getattr(g, "empresa_id", None)
