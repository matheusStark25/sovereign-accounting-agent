"""
Middleware de Segurança Integrado
==================================

Middleware que integra toda a camada de segurança ao Flask:
- Autenticação e autorização RBAC
- Criptografia automática de dados sensíveis
- Auditoria de todas as operações
- Proteção PII/LGPD
- Detecção de IDOR

Uso:
    from middleware.security import require_security, init_security

    # No app.py:
    init_security(app)

    # Nas rotas:
    @require_security(permission=Permission.READ_SENSITIVE_DATA)
    def minha_rota():
        ...
"""

import functools
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from flask import g, jsonify, request, make_response

from security import (
    AuditAction,
    Permission,
    Role,
)
from security.rbac_manager import SecurityError

__all__ = [
    "init_security",
    "require_security",
    "encrypt_response_data",
    "mask_pii_in_response",
    "get_current_tenant_id",
    "get_current_operator_id",
    "is_operator_admin",
]

logger = logging.getLogger(__name__)


# Instâncias globais (Singleton)
rbac_manager: Optional[Any] = None
audit_manager: Optional[Any] = None
pii_service: Optional[Any] = None
encryption_service: Optional[Any] = None


def init_security(app):
    """
    Inicializa a camada de segurança no Flask app.

    Args:
        app: Aplicação Flask
    """
    global rbac_manager, audit_manager, pii_service, encryption_service

    logger.info("Inicializando camada de segurança empresarial...")

    try:
        # Importa localmente para evitar problemas de import circular em runtime
        try:
            from security.rbac_manager import RBACManager
            from security.audit_trail_manager import AuditTrailManager
            from security.pii_protection_service import PIIProtectionService
            from security.encryption_service import EncryptionService
        except Exception as imp_e:
            logger.critical(
                f"Erro ao importar componentes de segurança: {imp_e}", exc_info=True
            )
            raise

        # Inicializa componentes (Singleton)
        rbac_manager = RBACManager()
        audit_manager = AuditTrailManager()
        pii_service = PIIProtectionService()
        encryption_service = EncryptionService()

        # Registra admin padrão se não existir
        _setup_default_admin()

        # Adiciona before_request handler
        app.before_request(_security_before_request)

        # Adiciona after_request handler
        app.after_request(_security_after_request)

        # Adiciona error handler for security exceptions
        app.register_error_handler(SecurityError, _handle_security_error)
        app.register_error_handler(PermissionError, _handle_permission_error)

        logger.info("✅ Camada de segurança inicializada com sucesso")

    except Exception as e:
        logger.critical(f"❌ FALHA ao inicializar segurança: {e}", exc_info=True)
        raise


def _setup_default_admin():
    """Configura admin padrão do sistema se não existir."""
    try:
        # Registra admin padrão para cada empresa
        empresas = ["EMPRESA_001", "EMPRESA_002"]  # Adicione suas empresas aqui

        for empresa_id in empresas:
            # Admin da empresa
            rbac_manager.register_operator(
                operator_id=f"ADMIN_{empresa_id}",
                tenant_id=empresa_id,
                roles={Role.TENANT_ADMIN},
                metadata={"email": f"admin@{empresa_id.lower()}.com"},
            )

            # Contador da empresa
            rbac_manager.register_operator(
                operator_id=f"CONTADOR_{empresa_id}",
                tenant_id=empresa_id,
                roles={Role.ACCOUNTANT},
                metadata={"email": f"contador@{empresa_id.lower()}.com"},
            )

        logger.info("Operadores padrão registrados")

    except Exception as e:
        logger.warning(f"Erro ao registrar operadores padrão: {e}")


def _security_before_request():
    """
    Handler executado ANTES de cada request.

    Extrai informações de tenant e operador dos headers.
    """
    # Extrai tenant_id e operator_id dos headers
    tenant_id = request.headers.get("X-Tenant-ID")
    operator_id = request.headers.get("X-Operator-ID")

    # Armazena no Flask g (contexto da requisição)
    g.tenant_id = tenant_id
    g.operator_id = operator_id
    g.request_start_time = datetime.now()

    # Log de debug
    if tenant_id and operator_id:
        logger.debug(f"Request iniciado: {operator_id}@{tenant_id}")


def _security_after_request(response):
    """
    Handler executado DEPOIS de cada request.

    Adiciona headers de segurança.
    """
    # Headers de segurança
    response.headers["X-Content-Type-Options"] = "nosnif"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )

    # Remove header Server (não expor versão)
    response.headers.pop("Server", None)

    return response


def _handle_security_error(error):
    """Handler para SecurityError."""
    logger.error(f"SecurityError: {error}")

    # Registra tentativa de violação no audit log
    if hasattr(g, "tenant_id") and g.tenant_id:
        try:
            audit_manager.log(
                tenant_id=g.tenant_id,
                operator_id=g.operator_id or "UNKNOWN",
                action=AuditAction.ACCESS_DENIED,
                resource_type="API",
                resource_id=request.endpoint or "unknown",
                status="BLOCKED",
                details={"error": str(error), "path": request.path},
            )
        except Exception as e:
            logger.error(f"Erro ao gravar audit log: {e}")

    return make_response(
        jsonify(
            {
                "error": "Acesso negado",
                "message": "Violação de segurança detectada",
                "code": "SECURITY_VIOLATION",
            }
        ),
        403,
    )


def _handle_permission_error(error):
    """Handler para PermissionError."""
    logger.warning(f"PermissionError: {error}")

    # Registra no audit log
    if hasattr(g, "tenant_id") and g.tenant_id:
        try:
            audit_manager.log(
                tenant_id=g.tenant_id,
                operator_id=g.operator_id or "UNKNOWN",
                action=AuditAction.ACCESS_DENIED,
                resource_type="API",
                resource_id=request.endpoint or "unknown",
                status="DENIED",
                details={"error": str(error), "path": request.path},
            )
        except Exception as e:
            logger.error(f"Erro ao gravar audit log: {e}")

    return make_response(
        jsonify(
            {
                "error": "Permissão negada",
                "message": str(error),
                "code": "PERMISSION_DENIED",
            }
        ),
        403,
    )


def require_security(
    permission: Permission,
    audit_action: Optional[str] = None,
    resource_type: str = "API",
):
    """
    Decorator para proteger rotas com RBAC e auditoria.

    Args:
        permission: Permissão necessária para acessar a rota
        audit_action: Ação de auditoria a ser registrada
        resource_type: Tipo de recurso sendo acessado

    Exemplo:
        @app.route("/api/v2/folha-pagamento", methods=["POST"])
        @require_security(
            permission=Permission.PROCESS_PAYROLL,
            audit_action=AuditAction.PROCESS_PAYROLL
        )
        def processar_folha():
            # tenant_id e operator_id estão em g
            ...
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Pega tenant_id e operator_id do contexto
            tenant_id = g.get("tenant_id")
            operator_id = g.get("operator_id")

            # Validação básica
            if not tenant_id or not operator_id:
                logger.warning(f"Request sem tenant/operator: {request.path}")
                return (
                    jsonify(
                        {
                            "error": "Headers de autenticação obrigatórios",
                            "required": ["X-Tenant-ID", "X-Operator-ID"],
                        }
                    ),
                    401,
                )

            # Valida permissão com RBAC
            try:
                rbac_manager.validate_access(
                    operator_id=operator_id,
                    tenant_id=tenant_id,
                    required_permission=permission,
                    resource_tenant_id=tenant_id,
                )
            except (PermissionError, SecurityError):
                # Os error handlers vão cuidar disso
                raise

            # Registra no audit log (antes de executar)
            audit_event_id = None
            if audit_action:
                try:
                    audit_event_id = audit_manager.log(
                        tenant_id=tenant_id,
                        operator_id=operator_id,
                        action=audit_action,
                        resource_type=resource_type,
                        resource_id=request.endpoint or "unknown",
                        status="STARTED",
                        details={
                            "method": request.method,
                            "path": request.path,
                            "ip": request.remote_addr,
                        },
                    )
                except Exception as e:
                    logger.error(f"Erro ao registrar audit log: {e}")

            # Executa a função protegida
            try:
                result = func(*args, **kwargs)

                # Atualiza audit log (sucesso)
                if audit_event_id:
                    try:
                        duration = (
                            datetime.now() - g.request_start_time
                        ).total_seconds()
                        audit_manager.log(
                            tenant_id=tenant_id,
                            operator_id=operator_id,
                            action=audit_action,
                            resource_type=resource_type,
                            resource_id=request.endpoint or "unknown",
                            status="SUCCESS",
                            details={"duration_seconds": duration, "http_status": 200},
                        )
                    except Exception as e:
                        logger.error(f"Erro ao atualizar audit log: {e}")

                return result

            except Exception as e:
                # Atualiza audit log (falha)
                if audit_event_id:
                    try:
                        duration = (
                            datetime.now() - g.request_start_time
                        ).total_seconds()
                        audit_manager.log(
                            tenant_id=tenant_id,
                            operator_id=operator_id,
                            action=audit_action,
                            resource_type=resource_type,
                            resource_id=request.endpoint or "unknown",
                            status="FAILED",
                            details={"error": str(e), "duration_seconds": duration},
                        )
                    except Exception as audit_error:
                        logger.error(f"Erro ao atualizar audit log: {audit_error}")

                # Re-raise para que Flask trate
                raise

        return wrapper

    return decorator


def encrypt_response_data(data: dict, fields: list) -> dict:
    """
    Criptografa campos específicos em um dict de resposta.

    Args:
        data: Dict com dados da resposta
        fields: Lista de campos a criptografar

    Returns:
        Dict com campos criptografados
    """
    encrypted = data.copy()

    for field in fields:
        if field in encrypted:
            try:
                original_value = encrypted[field]
                encrypted_value = encryption_service.encrypt(str(original_value))
                encrypted[field] = encrypted_value
                encrypted[f"{field}_encrypted"] = True
            except Exception as e:
                logger.error(f"Erro ao criptografar campo {field}: {e}")

    return encrypted


def mask_pii_in_response(data: dict, pii_fields: dict) -> dict:
    """
    Mascara dados PII em uma resposta.

    Args:
        data: Dict com dados da resposta
        pii_fields: Dict mapeando campo -> PIIType

    Returns:
        Dict com PII mascarado

    Exemplo:
        masked = mask_pii_in_response(
            data={"nome": "João", "cp": "12345678901"},
            pii_fields={"cpf": PIIType.CPF}
        )
    """
    masked = data.copy()

    for field, pii_type in pii_fields.items():
        if field in masked and masked[field]:
            try:
                masked[field] = pii_service.mask(masked[field], pii_type)
            except Exception as e:
                logger.error(f"Erro ao mascarar PII {field}: {e}")
    return masked


# Funções utilitárias para uso nas rotas
def get_current_tenant_id() -> str:
    """Retorna tenant_id do request atual."""
    return g.get("tenant_id")


def get_current_operator_id() -> str:
    """Retorna operator_id do request atual."""
    return g.get("operator_id")


def is_operator_admin() -> bool:
    """Verifica se operador atual é admin."""
    operator_id = get_current_operator_id()
    tenant_id = get_current_tenant_id()

    if not operator_id or not tenant_id:
        return False

    try:
        operator = rbac_manager._get_operator(operator_id, tenant_id)
        if operator:
            return (
                Role.SUPER_ADMIN in operator.roles
                or Role.TENANT_ADMIN in operator.roles
            )
    except Exception:
        pass

    return False
