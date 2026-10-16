"""
Rotas Seguras - Demonstração de Integração com Camada de Segurança
===================================================================

Exemplos de rotas protegidas com:
- RBAC (Role-Based Access Control)
- Auditoria automática
- Criptografia de dados
- Proteção PII/LGPD
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from middleware.security import (
    get_current_operator_id,
    get_current_tenant_id,
    is_operator_admin,
    mask_pii_in_response,
    require_security,
)
from security import (
    AuditAction,
    Permission,
    PIIType,
    SecureAccountingService,
)

logger = logging.getLogger(__name__)

# Blueprint de rotas seguras
secure_api_bp = Blueprint("secure_api", __name__, url_prefix="/api/v3/secure")


@secure_api_bp.route("/health", methods=["GET"])
def health():
    """Health check público (sem autenticação)"""
    return jsonify(
        {
            "status": "healthy",
            "service": "Secure API",
            "version": "1.0.0",
            "security_enabled": True,
        }
    )


@secure_api_bp.route("/whoami", methods=["GET"])
@require_security(
    permission=Permission.READ_SENSITIVE_DATA, audit_action=AuditAction.READ
)
def whoami():
    """
    Retorna informações do operador atual.

    Headers necessários:
        X-Tenant-ID: ID da empresa
        X-Operator-ID: ID do operador
    """
    return jsonify(
        {
            "tenant_id": get_current_tenant_id(),
            "operator_id": get_current_operator_id(),
            "is_admin": is_operator_admin(),
            "timestamp": datetime.now().isoformat(),
        }
    )


@secure_api_bp.route("/folha-pagamento", methods=["POST"])
@require_security(
    permission=Permission.PROCESS_PAYROLL,
    audit_action=AuditAction.PROCESS_PAYROLL,
    resource_type="PAYROLL",
)
def processar_folha():
    """
    Processa folha de pagamento com segurança total.

    Requer:
        - Permissão: PROCESS_PAYROLL
        - Headers: X-Tenant-ID, X-Operator-ID
        - Body: {"ano": 2026, "mes": 2, "funcionarios": [...]}

    Recursos:
        - Validação RBAC
        - Auditoria automática
        - Proteção IDOR
        - Criptografia de resultados
    """
    try:
        data = request.get_json()

        # Validar payload
        if not data or "funcionarios" not in data:
            return jsonify({"error": "Campo 'funcionarios' obrigatório"}), 400

        ano = data.get("ano", datetime.now().year)
        mes = data.get("mes", datetime.now().month)
        funcionarios = data["funcionarios"]

        # Usar SecureAccountingService
        service = SecureAccountingService(
            tenant_id=get_current_tenant_id(), operator_id=get_current_operator_id()
        )

        # Processar folha (com todas as proteções)
        resultado = service.process_payroll(
            empresa_id=get_current_tenant_id(),
            funcionarios=funcionarios,
            ano=ano,
            mes=mes,
            encrypt_results=True,  # Criptografa dados sensíveis
        )

        return jsonify(
            {
                "success": True,
                "message": "Folha processada com sucesso",
                "resultado": resultado,
                "metadata": {
                    "tenant_id": get_current_tenant_id(),
                    "operator_id": get_current_operator_id(),
                    "timestamp": datetime.now().isoformat(),
                },
            }
        )

    except Exception as e:
        logger.error(f"Erro ao processar folha: {e}", exc_info=True)
        return jsonify({"error": "Erro ao processar folha", "details": str(e)}), 500


@secure_api_bp.route("/funcionarios", methods=["GET"])
@require_security(
    permission=Permission.READ_SENSITIVE_DATA,
    audit_action=AuditAction.READ,
    resource_type="EMPLOYEES",
)
def listar_funcionarios():
    """
    Lista funcionários com PII mascarado.

    Demonstra:
        - Proteção automática de PII
        - Masking de CPF, email, telefone
        - RBAC para leitura de dados sensíveis
    """
    # Dados de exemplo (normalmente viria do banco)
    funcionarios = [
        {
            "id": 1,
            "nome": "João Silva",
            "cp": "12345678901",
            "email": "joao.silva@empresa.com",
            "telefone": "11987654321",
            "salario": 5000.00,
        },
        {
            "id": 2,
            "nome": "Maria Santos",
            "cp": "98765432109",
            "email": "maria.santos@empresa.com",
            "telefone": "11912345678",
            "salario": 6500.00,
        },
    ]

    # Mascara PII em cada funcionário
    funcionarios_mascarados = []
    for func in funcionarios:
        masked = mask_pii_in_response(
            data=func,
            pii_fields={
                "cp": PIIType.CPF,
                "email": PIIType.EMAIL,
                "telefone": PIIType.PHONE,
            },
        )
        funcionarios_mascarados.append(masked)

    return jsonify(
        {
            "funcionarios": funcionarios_mascarados,
            "total": len(funcionarios_mascarados),
            "pii_protected": True,
            "tenant_id": get_current_tenant_id(),
        }
    )


@secure_api_bp.route("/sped", methods=["POST"])
@require_security(
    permission=Permission.GENERATE_SPED,
    audit_action=AuditAction.GENERATE_SPED,
    resource_type="SPED",
)
def gerar_sped():
    """
    Gera SPED Contábil com segurança.

    Demonstra:
        - Permissão específica (GENERATE_SPED)
        - Auditoria de geração de documentos
        - Criptografia de conteúdo
    """
    try:
        data = request.get_json()

        # Validar payload
        if not data or "ano" not in data:
            return jsonify({"error": "Campo 'ano' obrigatório"}), 400

        ano = data["ano"]
        mes = data.get("mes")

        # Usar SecureAccountingService
        service = SecureAccountingService(
            tenant_id=get_current_tenant_id(), operator_id=get_current_operator_id()
        )

        # Gerar SPED (com auditoria)
        resultado = service.generate_sped(
            empresa_id=get_current_tenant_id(),
            ano=ano,
            mes=mes,
            encrypt_output=True,  # Criptografa arquivo gerado
        )

        return jsonify(
            {
                "success": True,
                "message": "SPED gerado com sucesso",
                "resultado": resultado,
                "metadata": {
                    "tenant_id": get_current_tenant_id(),
                    "operator_id": get_current_operator_id(),
                    "timestamp": datetime.now().isoformat(),
                },
            }
        )

    except Exception as e:
        logger.error(f"Erro ao gerar SPED: {e}", exc_info=True)
        return jsonify({"error": "Erro ao gerar SPED", "details": str(e)}), 500


@secure_api_bp.route("/audit-logs", methods=["GET"])
@require_security(
    permission=Permission.VIEW_AUDIT_LOGS,
    audit_action=AuditAction.READ,
    resource_type="AUDIT_LOGS",
)
def listar_audit_logs():
    """
    Lista logs de auditoria.

    Requer:
        - Permissão: VIEW_AUDIT_LOGS (apenas admins e auditores)

    Query params:
        - limit: Número máximo de logs (padrão: 100)
        - offset: Offset para paginação (padrão: 0)
    """
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))

        # Lê logs de auditoria do arquivo
        import json
        from pathlib import Path

        tenant_id = get_current_tenant_id()
        today = datetime.now().strftime("%Y-%m-%d")

        log_file = Path(f"logs/audit/{tenant_id}/{today}.log")

        if not log_file.exists():
            return jsonify(
                {"logs": [], "total": 0, "message": "Nenhum log disponível hoje"}
            )

        # Lê logs
        logs = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    log_entry = json.loads(line.strip())
                    logs.append(log_entry)
                except Exception:
                    continue

        # Paginação
        total = len(logs)
        paginated_logs = logs[offset : offset + limit]

        return jsonify(
            {
                "logs": paginated_logs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "tenant_id": tenant_id,
            }
        )

    except Exception as e:
        logger.error(f"Erro ao listar audit logs: {e}", exc_info=True)
        return jsonify({"error": "Erro ao listar logs", "details": str(e)}), 500


@secure_api_bp.route("/admin/users", methods=["GET"])
@require_security(
    permission=Permission.MANAGE_USERS,
    audit_action=AuditAction.READ,
    resource_type="USERS",
)
def listar_usuarios():
    """
    Lista usuários do tenant.

    Requer:
        - Permissão: MANAGE_USERS (apenas admins)
    """
    try:
        from security import RBACManager

        rbac = RBACManager()
        tenant_id = get_current_tenant_id()

        # Busca operadores do tenant
        operators = []
        for key, operator in rbac._operators.items():
            if operator.tenant_id == tenant_id:
                operators.append(
                    {
                        "operator_id": operator.operator_id,
                        "roles": [role.value for role in operator.roles],
                        "is_active": operator.is_active,
                        "created_at": operator.created_at.isoformat(),
                        "last_access": operator.last_access.isoformat(),
                    }
                )

        return jsonify(
            {"users": operators, "total": len(operators), "tenant_id": tenant_id}
        )

    except Exception as e:
        logger.error(f"Erro ao listar usuários: {e}", exc_info=True)
        return jsonify({"error": "Erro ao listar usuários", "details": str(e)}), 500


@secure_api_bp.route("/admin/stats", methods=["GET"])
@require_security(
    permission=Permission.CONFIGURE_SYSTEM,
    audit_action=AuditAction.READ,
    resource_type="SYSTEM_STATS",
)
def estatisticas_seguranca():
    """
    Retorna estatísticas de segurança do sistema.

    Requer:
        - Permissão: CONFIGURE_SYSTEM (apenas superadmin)
    """
    try:
        from security import RBACManager, VaultManager

        rbac = RBACManager()
        vault = VaultManager()

        stats = rbac.get_security_stats()
        vault_health = vault.health_check()

        return jsonify(
            {
                "rbac_stats": stats,
                "vault_health": vault_health,
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {e}", exc_info=True)
        return jsonify({"error": "Erro ao obter estatísticas", "details": str(e)}), 500
