"""
Auth Middleware - RBAC (Role-Based Access Control)
Implementa decorators de segurança para controle de acesso baseado em roles
"""

import logging
from functools import wraps
from typing import List, Optional

from flask import g, jsonify, request

logger = logging.getLogger(__name__)


class UnauthorizedError(Exception):
    """Exceção para acesso não autorizado"""

    def __init__(self, message: str = "Acesso não autorizado"):
        self.message = message
        super().__init__(self.message)


class ForbiddenError(Exception):
    """Exceção para operação proibida"""

    def __init__(self, message: str = "Operação não permitida"):
        self.message = message
        super().__init__(self.message)


def get_current_user() -> Optional[dict]:
    """
    Extrai dados do usuário autenticado do contexto da requisição

    Returns:
        Dict com user_id, username, email, roles e tenant_id
        None se não autenticado

    Exemplo:
        {
            'user_id': 'usr_12345',
            'username': 'joao.silva',
            'email': 'joao@empresa.com',
            'roles': ['contador', 'admin'],
            'tenant_id': 'tenant_abc123'
        }
    """
    # Em produção, extrair de JWT token ou sessão
    # Por enquanto, extrair de headers para desenvolvimento

    if hasattr(g, "current_user"):
        return g.current_user

    # Extrair de headers (substituir por JWT em produção)
    user_id = request.headers.get("X-User-ID")
    username = request.headers.get("X-Username")
    email = request.headers.get("X-User-Email")
    roles_header = request.headers.get("X-User-Roles", "")
    tenant_id = request.headers.get("X-Tenant-ID")

    if not user_id or not tenant_id:
        return None

    # Parse roles (formato: "contador,admin")
    roles = [r.strip() for r in roles_header.split(",") if r.strip()]

    user_data = {
        "user_id": user_id,
        "username": username or "desconhecido",
        "email": email or "",
        "roles": roles,
        "tenant_id": tenant_id,
    }

    # Cache no contexto da requisição
    g.current_user = user_data

    logger.debug(
        f"Usuário autenticado: {username} (ID: {user_id}) - Roles: {roles} - Tenant: {tenant_id}"
    )

    return user_data


def require_role(allowed_roles: List[str]):
    """
    Decorator RBAC - Valida se o usuário possui uma das roles permitidas

    Args:
        allowed_roles: Lista de roles permitidas (ex: ['contador', 'admin'])

    Raises:
        UnauthorizedError: Se usuário não autenticado
        ForbiddenError: Se usuário não possui role necessária

    Exemplo:
        @app.route('/api/v1/calculo/rescisao', methods=['POST'])
        @require_role(['contador', 'admin'])
        def calcular_rescisao():
            # Apenas contadores e admins podem acessar
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. Verificar autenticação
            user = get_current_user()

            if not user:
                logger.info(
                    f"Tentativa de acesso não autenticado: {request.method} {request.path}"
                )
                raise UnauthorizedError(
                    "Autenticação necessária. Forneça credenciais válidas."
                )

            # 2. Verificar role
            user_roles = user.get("roles", [])
            has_permission = any(role in allowed_roles for role in user_roles)

            if not has_permission:
                logger.info(
                    f"Acesso negado para {user['username']} (ID: {user['user_id']}) - "
                    f"Roles: {user_roles} - Requerido: {allowed_roles} - "
                    f"Endpoint: {request.method} {request.path}"
                )
                raise ForbiddenError(
                    f"Acesso negado. Roles permitidas: {', '.join(allowed_roles)}. "
                    f"Suas roles: {', '.join(user_roles) if user_roles else 'nenhuma'}"
                )

            # 3. Log de auditoria
            logger.info(
                f"✅ Acesso autorizado: {user['username']} ({user['user_id']}) - "
                f"Role: {user_roles[0] if user_roles else 'N/A'} - "
                f"Tenant: {user['tenant_id']} - "
                f"Endpoint: {request.method} {request.path}"
            )

            # 4. Executar função protegida
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_authentication(f):
    """
    Decorator simples - Apenas valida se o usuário está autenticado (qualquer role)

    Exemplo:
        @app.route('/api/v1/profile', methods=['GET'])
        @require_authentication
        def get_profile():
            # Qualquer usuário autenticado pode acessar
            ...
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()

        if not user:
            logger.info(f"Acesso não autenticado: {request.method} {request.path}")
            raise UnauthorizedError("Autenticação necessária")

        logger.debug(
            f"Usuário autenticado: {user['username']} - "
            f"Endpoint: {request.method} {request.path}"
        )

        return f(*args, **kwargs)

    return decorated_function


# Error handlers para Flask
def register_auth_error_handlers(app):
    """
    Registra handlers de erro para exceções de autenticação/autorização

    Args:
        app: Instância Flask

    Uso:
        from api.middleware.auth import register_auth_error_handlers
        register_auth_error_handlers(app)
    """

    @app.errorhandler(UnauthorizedError)
    def handle_unauthorized(error):
        """Handler para erro 401"""
        logger.info(f"401 Unauthorized: {error.message}")
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Unauthorized",
                    "message": error.message,
                    "status_code": 401,
                    "tipo": "autenticacao",
                }
            ),
            401,
        )

    @app.errorhandler(ForbiddenError)
    def handle_forbidden(error):
        """Handler para erro 403"""
        logger.info(f"403 Forbidden: {error.message}")
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Forbidden",
                    "message": error.message,
                    "status_code": 403,
                    "tipo": "autorizacao",
                }
            ),
            403,
        )
