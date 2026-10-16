"""
RBACManager - Controle de Acesso Baseado em Funções (Multi-Tenant)
===================================================================

Sistema de autorização de nível empresarial com:
- Isolamento estrito por tenant_id
- Controle de acesso baseado em funções (RBAC)
- Proteção contra IDOR (Insecure Direct Object Reference)
- Auditoria de tentativas de acesso não autorizado
- Caching de permissões para performance

Princípios:
- Default Deny (negação por padrão)
- Validação dupla (tenant + role)
- Alerta em tentativas de acesso cruzado
- Thread-safe para ambientes concorrentes
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class Role(Enum):
    """Papéis disponíveis no sistema."""

    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    ACCOUNTANT = "accountant"
    AUDITOR = "auditor"
    VIEWER = "viewer"
    GUEST = "guest"


class Permission(Enum):
    """Permissões granulares do sistema."""

    # Operações de dados
    READ_SENSITIVE_DATA = "read_sensitive_data"
    # Backwards-compatible alias
    READ_DATA = READ_SENSITIVE_DATA
    WRITE_DATA = "write_data"
    DELETE_DATA = "delete_data"

    # Operações contábeis
    PROCESS_PAYROLL = "process_payroll"
    GENERATE_SPED = "generate_sped"
    SIGN_DOCUMENTS = "sign_documents"

    # Administração
    MANAGE_USERS = "manage_users"
    MANAGE_TENANTS = "manage_tenants"
    VIEW_AUDIT_LOGS = "view_audit_logs"

    # Configurações
    CONFIGURE_SYSTEM = "configure_system"
    ROTATE_KEYS = "rotate_keys"


@dataclass
class OperatorContext:
    """Contexto de um operador (usuário)."""

    operator_id: str
    tenant_id: str
    roles: Set[Role] = field(default_factory=set)
    permissions: Set[Permission] = field(default_factory=set)
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_access: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)


class RBACManager:
    """
    Gerenciador de Controle de Acesso Baseado em Funções (Singleton).

    Features:
    - Isolamento multi-tenant
    - Validação de permissões
    - Detecção de IDOR
    - Caching de permissões
    - Auditoria de acessos
    """

    _instance = None
    _lock = Lock()
    _initialized = False

    # Mapeamento de roles para permissões
    ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
        Role.SUPER_ADMIN: {
            Permission.READ_SENSITIVE_DATA,
            Permission.WRITE_DATA,
            Permission.DELETE_DATA,
            Permission.PROCESS_PAYROLL,
            Permission.GENERATE_SPED,
            Permission.SIGN_DOCUMENTS,
            Permission.MANAGE_USERS,
            Permission.MANAGE_TENANTS,
            Permission.VIEW_AUDIT_LOGS,
            Permission.CONFIGURE_SYSTEM,
            Permission.ROTATE_KEYS,
        },
        Role.TENANT_ADMIN: {
            Permission.READ_SENSITIVE_DATA,
            Permission.WRITE_DATA,
            Permission.DELETE_DATA,
            Permission.PROCESS_PAYROLL,
            Permission.GENERATE_SPED,
            Permission.SIGN_DOCUMENTS,
            Permission.MANAGE_USERS,
            Permission.VIEW_AUDIT_LOGS,
        },
        Role.ACCOUNTANT: {
            Permission.READ_SENSITIVE_DATA,
            Permission.WRITE_DATA,
            Permission.PROCESS_PAYROLL,
            Permission.GENERATE_SPED,
            Permission.SIGN_DOCUMENTS,
        },
        Role.AUDITOR: {
            Permission.READ_SENSITIVE_DATA,
            Permission.VIEW_AUDIT_LOGS,
        },
        Role.VIEWER: {
            # Sem READ_SENSITIVE_DATA (apenas dados públicos)
        },
        Role.GUEST: set(),
    }

    # Cache TTL
    CACHE_TTL_SECONDS = 300  # 5 minutos

    def __new__(cls):
        """Implementa singleton pattern (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Inicializa o gerenciador RBAC (apenas uma vez)."""
        # Evita reinicialização
        if self._initialized:
            return

        with self._lock:
            if not self._initialized:
                self._operators: Dict[str, OperatorContext] = {}
                self._permission_cache: Dict[str, Tuple[Set[Permission], datetime]] = {}
                self._instance_lock = Lock()  # Lock para operações de instância
                self._failed_access_attempts: Dict[str, List[datetime]] = {}
                self._initialize_default_operators()
                self._initialized = True
                logger.info("RBACManager inicializado com sucesso")

    def _initialize_default_operators(self) -> None:
        """Inicializa operadores padrão do sistema."""
        # Super Admin padrão (somente para setup inicial)
        self.register_operator(
            operator_id="SYSTEM_ADMIN", tenant_id="SYSTEM", roles={Role.SUPER_ADMIN}
        )

    def register_operator(
        self,
        operator_id: str,
        tenant_id: str,
        roles: Set[Role],
        is_active: bool = True,
        metadata: Optional[Dict] = None,
    ) -> OperatorContext:
        """
        Registra um novo operador no sistema.

        Args:
            operator_id: ID único do operador
            tenant_id: ID do tenant (organização)
            roles: Conjunto de roles do operador
            is_active: Se operador está ativo
            metadata: Metadados adicionais

        Returns:
            Contexto do operador criado
        """
        with self._instance_lock:
            # Calcula permissões com base nos roles
            permissions = set()
            for role in roles:
                permissions.update(self.ROLE_PERMISSIONS.get(role, set()))

            # Cria contexto
            operator = OperatorContext(
                operator_id=operator_id,
                tenant_id=tenant_id,
                roles=roles,
                permissions=permissions,
                is_active=is_active,
                metadata=metadata or {},
            )

            # Armazena
            key = f"{tenant_id}:{operator_id}"
            self._operators[key] = operator

            logger.info(
                f"Operador registrado: {operator_id} @ {tenant_id} "
                f"(roles: {[r.value for r in roles]})"
            )

            return operator

    def validate_access(
        self,
        operator_id: str,
        tenant_id: str,
        required_permission: Optional[Permission] = None,
        resource_tenant_id: Optional[str] = None,
        permission: Optional[Permission] = None,
    ) -> bool:
        """
        Valida se operador tem permissão para ação no tenant.

        Args:
            operator_id: ID do operador
            tenant_id: ID do tenant do operador
            required_permission: Permissão necessária
            resource_tenant_id: ID do tenant do recurso (para validar IDOR)

        Returns:
            True se acesso permitido

        Raises:
            PermissionError: Se acesso negado
            SecurityError: Se tentativa de IDOR detectada
        """
        try:
            # Compatibility: allow caller to pass `permission=` or positional `required_permission`
            if required_permission is None and permission is not None:
                required_permission = permission

            # 1. Obtém contexto do operador
            operator = self._get_operator(operator_id, tenant_id)

            if not operator:
                self._log_access_denied(operator_id, tenant_id, "OPERATOR_NOT_FOUND")
                raise PermissionError(f"Operador {operator_id} não encontrado")

            # 2. Valida se operador está ativo
            if not operator.is_active:
                self._log_access_denied(operator_id, tenant_id, "OPERATOR_INACTIVE")
                raise PermissionError(f"Operador {operator_id} está inativo")

            # 3. PROTEÇÃO IDOR: Valida se operador está acessando recurso do próprio tenant
            if resource_tenant_id and resource_tenant_id != tenant_id:
                # Exceção: SUPER_ADMIN pode acessar qualquer tenant
                if Role.SUPER_ADMIN not in operator.roles:
                    self._log_idor_attempt(operator_id, tenant_id, resource_tenant_id)
                    raise SecurityError(
                        f"IDOR detectado: Operador {operator_id} do tenant {tenant_id} "
                        f"tentou acessar recurso do tenant {resource_tenant_id}"
                    )

            # 4. Valida permissão
            if required_permission not in operator.permissions:
                self._log_access_denied(
                    operator_id,
                    tenant_id,
                    f"MISSING_PERMISSION:{required_permission.value}",
                )
                raise PermissionError(
                    f"Operador {operator_id} não tem permissão: {required_permission.value}"
                )

            # 5. Atualiza último acesso
            operator.last_access = datetime.now()

            logger.debug(
                f"Acesso concedido: {operator_id}@{tenant_id} → {required_permission.value}"
            )

            return True

        except (PermissionError, SecurityError):
            raise
        except Exception as e:
            logger.error(f"Erro na validação de acesso: {e}", exc_info=True)
            raise PermissionError("Erro ao validar permissões")

    def has_permission(
        self, operator_id: str, tenant_id: str, permission: Permission
    ) -> bool:
        """
        Verifica se operador tem permissão (retorna bool sem exception).

        Args:
            operator_id: ID do operador
            tenant_id: ID do tenant
            permission: Permissão a verificar

        Returns:
            True se tem permissão
        """
        try:
            return self.validate_access(operator_id, tenant_id, permission)
        except (PermissionError, SecurityError):
            return False

    # Backwards-compatible method name expected by some tests
    def get_permissions(
        self, operator_id: str, tenant_id: str, use_cache: bool = True
    ) -> Set[Permission]:
        return self.get_operator_permissions(
            operator_id, tenant_id, use_cache=use_cache
        )

    def get_operator_permissions(
        self, operator_id: str, tenant_id: str, use_cache: bool = True
    ) -> Set[Permission]:
        """
        Retorna permissões de um operador (com cache).

        Args:
            operator_id: ID do operador
            tenant_id: ID do tenant
            use_cache: Se deve usar cache

        Returns:
            Conjunto de permissões
        """
        cache_key = f"{tenant_id}:{operator_id}"

        # Verifica cache
        if use_cache and cache_key in self._permission_cache:
            permissions, cached_at = self._permission_cache[cache_key]
            if (datetime.now() - cached_at).total_seconds() < self.CACHE_TTL_SECONDS:
                return permissions

        # Obtém permissões atualizadas
        operator = self._get_operator(operator_id, tenant_id)
        if not operator:
            return set()

        # Atualiza cache
        self._permission_cache[cache_key] = (operator.permissions, datetime.now())

        return operator.permissions

    def _get_operator(
        self, operator_id: str, tenant_id: str
    ) -> Optional[OperatorContext]:
        """Recupera contexto de um operador."""
        key = f"{tenant_id}:{operator_id}"
        return self._operators.get(key)

    def _log_access_denied(self, operator_id: str, tenant_id: str, reason: str) -> None:
        """Registra tentativa de acesso negado."""
        logger.info(f"Acesso NEGADO: {operator_id}@{tenant_id} - Motivo: {reason}")

        # Rastreia tentativas falhas
        key = f"{tenant_id}:{operator_id}"
        if key not in self._failed_access_attempts:
            self._failed_access_attempts[key] = []
        self._failed_access_attempts[key].append(datetime.now())

        # Alerta se muitas tentativas falhas
        recent_fails = [
            t
            for t in self._failed_access_attempts[key]
            if (datetime.now() - t).total_seconds() < 300  # Últimas 5 min
        ]
        if len(recent_fails) >= 5:
            logger.critical(
                f"ALERTA: {operator_id}@{tenant_id} teve {len(recent_fails)} "
                "tentativas de acesso negado nos últimos 5 minutos!"
            )

    def _log_idor_attempt(
        self, operator_id: str, operator_tenant: str, resource_tenant: str
    ) -> None:
        """Registra tentativa de IDOR (acesso cruzado)."""
        logger.critical(
            f"🚨 IDOR DETECTADO: Operador {operator_id} do tenant {operator_tenant} "
            f"tentou acessar recurso do tenant {resource_tenant}! "
            "Bloqueio aplicado."
        )

        # Em produção, aqui você dispararia:
        # - Email para equipe de segurança
        # - Webhook para SIEM
        # - Possível bloqueio temporário do operador

    def deactivate_operator(self, operator_id: str, tenant_id: str) -> None:
        """Desativa um operador."""
        operator = self._get_operator(operator_id, tenant_id)
        if operator:
            operator.is_active = False
            logger.info(f"Operador desativado: {operator_id}@{tenant_id}")

    def clear_permission_cache(self) -> None:
        """Limpa cache de permissões."""
        with self._instance_lock:
            self._permission_cache.clear()
            logger.info("Cache de permissões limpo")

    def get_security_stats(self) -> Dict:
        """
        Retorna estatísticas de segurança.

        Returns:
            Dict com estatísticas
        """
        total_operators = len(self._operators)
        active_operators = sum(1 for op in self._operators.values() if op.is_active)

        # Conta tentativas falhas recentes
        recent_fails = sum(
            len([t for t in attempts if (datetime.now() - t).total_seconds() < 3600])
            for attempts in self._failed_access_attempts.values()
        )

        return {
            "total_operators": total_operators,
            "active_operators": active_operators,
            "inactive_operators": total_operators - active_operators,
            "failed_attempts_last_hour": recent_fails,
            "cache_size": len(self._permission_cache),
        }


class SecurityError(Exception):
    """Exceção para violações de segurança (IDOR, etc)."""

    pass
