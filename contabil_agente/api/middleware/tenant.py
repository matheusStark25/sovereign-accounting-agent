"""
Tenant Middleware - Multi-tenancy e Isolamento de Dados
Garante que dados de uma empresa nunca vazem para outra
"""

import logging
from functools import wraps

from flask import g, jsonify, request

from .auth import get_current_user

logger = logging.getLogger(__name__)


class TenantIsolationError(Exception):
    """Exceção para violação de isolamento de tenant"""

    def __init__(self, message: str = "Violação de isolamento de dados"):
        self.message = message
        super().__init__(self.message)


def get_tenant_context() -> dict:
    """
    Extrai contexto do tenant da requisição

    Returns:
        Dict com tenant_id e metadados do tenant

    Exemplo:
        {
            'tenant_id': 'tenant_abc123',
            'tenant_name': 'Empresa XYZ Ltda',
            'cnpj': '12.345.678/0001-90',
            'plan': 'premium'
        }
    """
    if hasattr(g, "tenant_context"):
        return g.tenant_context

    user = get_current_user()
    if not user:
        return {}

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        logger.error("Usuário autenticado sem tenant_id!")
        return {}

    # Em produção, buscar metadados do tenant no banco de dados
    # Por enquanto, retornar estrutura básica
    tenant_context = {
        "tenant_id": tenant_id,
        "tenant_name": request.headers.get("X-Tenant-Name", "Desconhecido"),
        "cnpj": request.headers.get("X-Tenant-CNPJ", ""),
        "plan": request.headers.get("X-Tenant-Plan", "basic"),
    }

    # Cache no contexto
    g.tenant_context = tenant_context

    logger.debug(f"Tenant context: {tenant_id} - {tenant_context['tenant_name']}")

    return tenant_context


def validate_tenant(resource_tenant_id: str, operation: str = "acesso") -> bool:
    """
    Valida se o tenant atual tem permissão para acessar um recurso

    Args:
        resource_tenant_id: ID do tenant dono do recurso
        operation: Descrição da operação para logs (ex: 'leitura', 'modificação')

    Returns:
        True se permitido

    Raises:
        TenantIsolationError: Se houver violação de isolamento

    Exemplo:
        # Antes de retornar dados de um funcionário
        validate_tenant(funcionario.tenant_id, operation='consulta de funcionário')
    """
    user = get_current_user()
    if not user:
        raise TenantIsolationError("Usuário não autenticado")

    user_tenant_id = user.get("tenant_id")

    if user_tenant_id != resource_tenant_id:
        logger.error(
            f"🚨 VIOLAÇÃO DE ISOLAMENTO! Usuário {user['user_id']} (Tenant: {user_tenant_id}) "
            f"tentou {operation} de recurso do Tenant: {resource_tenant_id}"
        )
        raise TenantIsolationError(
            f"Acesso negado. Você não tem permissão para {operation} deste recurso."
        )

    logger.debug(f"✅ Validação de tenant OK: {user_tenant_id} - Operação: {operation}")
    return True


def require_tenant_isolation(f):
    """
    Decorator - Valida automaticamente tenant_id de payloads JSON

    Verifica se o tenant_id enviado no body corresponde ao tenant do usuário

    Exemplo:
        @app.route('/api/v1/funcionarios', methods=['POST'])
        @require_role(['admin'])
        @require_tenant_isolation
        def criar_funcionario():
            # Garante que request.json['tenant_id'] == current_user.tenant_id
            ...
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            raise TenantIsolationError("Usuário não autenticado")

        user_tenant_id = user.get("tenant_id")

        # Verificar tenant_id no JSON body (se existir)
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            payload_tenant_id = payload.get("tenant_id")

            if payload_tenant_id and payload_tenant_id != user_tenant_id:
                logger.error(
                    "🚨 Tentativa de criar recurso para outro tenant! "
                    f"Usuário: {user['user_id']} (Tenant: {user_tenant_id}) - "
                    f"Tentou criar para Tenant: {payload_tenant_id}"
                )
                raise TenantIsolationError(
                    "Violação de segurança. Você só pode criar recursos para seu próprio tenant."
                )

            # Se não veio tenant_id, injetar automaticamente
            if not payload_tenant_id:
                payload["tenant_id"] = user_tenant_id
                request._cached_json = (payload, payload)  # Atualizar cache
                logger.debug(f"Tenant ID injetado automaticamente: {user_tenant_id}")

        # Verificar tenant_id em query params
        query_tenant_id = request.args.get("tenant_id")
        if query_tenant_id and query_tenant_id != user_tenant_id:
            logger.error(
                "🚨 Query param tenant_id não corresponde ao usuário! "
                f"Usuário: {user_tenant_id} - Query: {query_tenant_id}"
            )
            raise TenantIsolationError(
                "Parâmetro tenant_id inválido. Use seu próprio tenant."
            )

        logger.debug(
            f"✅ Validação de isolamento OK - Tenant: {user_tenant_id} - "
            f"Endpoint: {request.method} {request.path}"
        )

        return f(*args, **kwargs)

    return decorated_function


# Error handler
def register_tenant_error_handlers(app):
    """
    Registra handler de erro para violações de isolamento

    Args:
        app: Instância Flask
    """

    @app.errorhandler(TenantIsolationError)
    def handle_tenant_isolation(error):
        """Handler para violação de isolamento"""
        logger.error(f"🚨 Violação de Isolamento: {error.message}")
        return (
            jsonify(
                {
                    "error": "Tenant Isolation Violation",
                    "message": error.message,
                    "status_code": 403,
                    "tipo": "isolamento_dados",
                }
            ),
            403,
        )
