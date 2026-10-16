"""
SecureAccountingService - Serviço Contábil com Segurança Integrada
===================================================================

Serviço principal do sistema contábil com camada de segurança completa:
- Auto-configuração plug-and-play
- Isolamento multi-tenant
- Criptografia transparente
- Auditoria automática
- Proteção PII/LGPD
- Fail-safe robusto

Uso:
    service = SecureAccountingService(
        tenant_id="EMPRESA_001",
        operator_id="CONTADOR_123"
    )

    # Todas as operações são automaticamente:
    # - Autorizadas (RBAC)
    # - Criptografadas (AES-256)
    # - Auditadas (HMAC)
    # - Protegidas (PII masking)
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from .audit_trail_manager import AuditAction, AuditSeverity, AuditTrailManager
from .encryption_service import EncryptionService
from .pii_protection_service import PIIProtectionService
from .rbac_manager import Permission, RBACManager, SecurityError
from .vault_manager import VaultManager

logger = logging.getLogger(__name__)


class SecureAccountingService:
    """
    Serviço contábil com segurança de nível empresarial.

    Features:
    - Plug-and-play (auto-configuração)
    - Multi-tenant com isolamento
    - RBAC com proteção IDOR
    - Criptografia AES-256
    - Audit trail imutável
    - Proteção PII/LGPD
    - Fail-safe robusto
    """

    def __init__(
        self,
        tenant_id: str,
        operator_id: str,
        session_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ):
        """
        Inicializa serviço contábil seguro (auto-provisioning).

        Args:
            tenant_id: ID do tenant (empresa)
            operator_id: ID do operador (usuário)
            session_id: ID da sessão (opcional)
            ip_address: IP do cliente (opcional)
        """
        self.tenant_id = tenant_id
        self.operator_id = operator_id
        self.session_id = session_id
        self.ip_address = ip_address

        # Inicializa componentes de segurança
        try:
            logger.info(f"🔐 Inicializando SecureAccountingService para {tenant_id}...")

            # 1. Vault (secrets)
            self.vault = VaultManager()
            logger.info("✓ VaultManager inicializado")

            # 2. Encryption
            self.encryption = EncryptionService(self.vault)
            logger.info("✓ EncryptionService inicializado (AES-256-GCM)")

            # 3. RBAC
            self.rbac = RBACManager()
            logger.info("✓ RBACManager inicializado (Multi-tenant)")

            # 4. PII Protection
            self.pii = PIIProtectionService()
            logger.info("✓ PIIProtectionService inicializado (LGPD/GDPR)")

            # 5. Audit Trail
            self.audit = AuditTrailManager(self.vault)
            logger.info("✓ AuditTrailManager inicializado (Imutável)")

            # Log de inicialização
            self._log_audit(
                action=AuditAction.LOGIN,
                description=f"Serviço inicializado para tenant {tenant_id}",
                severity=AuditSeverity.INFO,
            )

            logger.info(
                "✅ SecureAccountingService PRONTO | "
                f"Tenant: {tenant_id} | Operator: {operator_id}"
            )

        except Exception as e:
            logger.critical(
                f"❌ FALHA CRÍTICA ao inicializar SecureAccountingService: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Sistema não pode iniciar: {e}")

    @contextmanager
    def secure_operation(
        self,
        action: AuditAction,
        required_permission: Permission,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        description: str = "",
    ):
        """
        Context manager para operações seguras.

        Executa:
        1. Valida permissão (RBAC)
        2. Audita início
        3. Executa operação (yield)
        4. Audita sucesso/falha
        5. Fail-safe em caso de erro

        Usage:
            with service.secure_operation(
                action=AuditAction.PROCESS_PAYROLL,
                required_permission=Permission.PROCESS_PAYROLL,
                resource="folha_pagamento",
                resource_id="202602"
            ):
                # Código da operação
                result = processar_folha()
                return result
        """
        error = None
        success = False

        try:
            # 1. Validação de permissão (RBAC)
            self._validate_permission(
                required_permission, resource_tenant_id=self.tenant_id
            )

            # 2. Auditoria: início da operação
            self._log_audit(
                action=action,
                resource=resource,
                resource_id=resource_id,
                description=f"Iniciando: {description}",
                severity=AuditSeverity.INFO,
            )

            # 3. Executa operação
            yield self

            # 4. Se chegou aqui, sucesso
            success = True

        except SecurityError as e:
            # Violação de segurança (IDOR, etc)
            error = e
            logger.critical(f"VIOLAÇÃO DE SEGURANÇA: {e}")
            self._graceful_shutdown(action, str(e))
            raise

        except PermissionError as e:
            # Permissão negada
            error = e
            logger.warning(f"Permissão negada: {e}")
            raise

        except Exception as e:
            # Erro genérico
            error = e
            logger.error(f"Erro em operação segura: {e}", exc_info=True)
            raise

        finally:
            # 5. Auditoria: resultado final
            self._log_audit(
                action=action,
                resource=resource,
                resource_id=resource_id,
                description=f"{'Concluído' if success else 'Falhou'}: {description}",
                success=success,
                severity=AuditSeverity.INFO if success else AuditSeverity.ERROR,
                error_message=str(error) if error else None,
            )

    def encrypt_sensitive_data(
        self, data: Dict[str, Any], sensitive_fields: List[str]
    ) -> Dict[str, Any]:
        """
        Criptografa campos sensíveis de um dicionário.

        Args:
            data: Dicionário com dados
            sensitive_fields: Lista de campos a criptografar

        Returns:
            Dicionário com campos criptografados
        """
        try:
            encrypted_data = self.encryption.encrypt_dict(
                data, fields_to_encrypt=sensitive_fields
            )

            self._log_audit(
                action=AuditAction.ENCRYPTION,
                description=f"Criptografados {len(sensitive_fields)} campos",
                severity=AuditSeverity.INFO,
            )

            return encrypted_data

        except Exception as e:
            logger.error(f"Erro ao criptografar dados: {e}")
            self._log_audit(
                action=AuditAction.ENCRYPTION,
                description=f"Falha na criptografia: {e}",
                success=False,
                severity=AuditSeverity.ERROR,
            )
            raise

    def decrypt_sensitive_data(
        self, data: Dict[str, Any], fields_to_decrypt: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Descriptografa campos de um dicionário.

        Args:
            data: Dicionário com dados criptografados
            fields_to_decrypt: Campos a descriptografar (None = auto)

        Returns:
            Dicionário com campos descriptografados
        """
        try:
            # Valida permissão para acessar dados sensíveis
            self._validate_permission(Permission.READ_SENSITIVE_DATA)

            decrypted_data = self.encryption.decrypt_dict(
                data, fields_to_decrypt=fields_to_decrypt
            )

            self._log_audit(
                action=AuditAction.DECRYPTION,
                description="Dados descriptografados",
                severity=AuditSeverity.INFO,
            )

            return decrypted_data

        except Exception as e:
            logger.error(f"Erro ao descriptografar dados: {e}")
            self._log_audit(
                action=AuditAction.DECRYPTION,
                description=f"Falha na descriptografia: {e}",
                success=False,
                severity=AuditSeverity.ERROR,
            )
            raise

    def mask_pii_for_display(
        self, data: Dict[str, Any], fields_to_mask: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Aplica masking em dados PII para exibição.

        Args:
            data: Dicionário com dados
            fields_to_mask: Campos a mascarar (None = auto-detecta)

        Returns:
            Dicionário com dados mascarados
        """
        try:
            masked_data = self.pii.apply_pii_masking(
                data, fields_to_mask=fields_to_mask
            )

            self._log_audit(
                action=AuditAction.PII_ACCESS,
                description="Dados PII mascarados para visualização",
                severity=AuditSeverity.INFO,
            )

            return masked_data

        except Exception as e:
            logger.error(f"Erro ao mascarar PII: {e}")
            raise

    def process_payroll(
        self,
        empresa_id: str,
        mes: int,
        ano: int,
        funcionarios: List[Dict],
        encrypt_results: bool = True,
    ) -> Dict[str, Any]:
        """
        Processa folha de pagamento com segurança completa.

        Args:
            empresa_id: ID da empresa
            mes: Mês de referência
            ano: Ano de referência
            funcionarios: Lista de funcionários
            encrypt_results: Se deve criptografar resultados

        Returns:
            Resultado do processamento
        """
        with self.secure_operation(
            action=AuditAction.PROCESS_PAYROLL,
            required_permission=Permission.PROCESS_PAYROLL,
            resource="folha_pagamento",
            resource_id=f"{empresa_id}_{ano}{mes:02d}",
            description=f"Processamento de folha {ano}/{mes}",
        ):
            try:
                # Valida tenant
                self._validate_tenant_access(empresa_id)

                # Processa cada funcionário
                results = []
                for func in funcionarios:
                    # Mascara dados sensíveis no log
                    func_masked = self.pii.apply_pii_masking(func)
                    logger.info(
                        f"Processando funcionário: {func_masked.get('nome', 'N/A')}"
                    )

                    # Aqui iria a lógica real de cálculo de folha
                    # (omitido por brevidade)

                    result = {
                        "funcionario_id": func.get("id"),
                        "salario_bruto": func.get("salario"),
                        "descontos": 0.0,
                        "salario_liquido": func.get("salario", 0.0),
                    }

                    # Criptografa se solicitado
                    if encrypt_results:
                        result = self.encrypt_sensitive_data(
                            result,
                            sensitive_fields=["salario_bruto", "salario_liquido"],
                        )

                    results.append(result)

                return {
                    "empresa_id": empresa_id,
                    "periodo": f"{ano}-{mes:02d}",
                    "total_funcionarios": len(funcionarios),
                    "resultados": results,
                    "processed_at": datetime.now().isoformat(),
                }

            except Exception as e:
                logger.error(f"Erro processando folha: {e}", exc_info=True)
                raise

    def generate_sped(
        self, empresa_id: str, tipo_sped: str, periodo: str
    ) -> Dict[str, Any]:
        """
        Gera arquivo SPED com auditoria.

        Args:
            empresa_id: ID da empresa
            tipo_sped: Tipo de SPED (Contábil, Fiscal, etc)
            periodo: Período de referência

        Returns:
            Resultado da geração
        """
        with self.secure_operation(
            action=AuditAction.GENERATE_SPED,
            required_permission=Permission.GENERATE_SPED,
            resource="sped",
            resource_id=f"{empresa_id}_{tipo_sped}_{periodo}",
            description=f"Geração de SPED {tipo_sped}",
        ):
            try:
                # Valida tenant
                self._validate_tenant_access(empresa_id)

                # Aqui iria a lógica real de geração de SPED
                # (omitido por brevidade)

                return {
                    "empresa_id": empresa_id,
                    "tipo_sped": tipo_sped,
                    "periodo": periodo,
                    "status": "gerado",
                    "generated_at": datetime.now().isoformat(),
                }

            except Exception as e:
                logger.error(f"Erro gerando SPED: {e}", exc_info=True)
                raise

    def _validate_permission(
        self, required_permission: Permission, resource_tenant_id: Optional[str] = None
    ) -> None:
        """
        Valida se operador tem permissão.

        Args:
            required_permission: Permissão necessária
            resource_tenant_id: ID do tenant do recurso

        Raises:
            PermissionError: Se permissão negada
            SecurityError: Se tentativa de IDOR
        """
        try:
            self.rbac.validate_access(
                operator_id=self.operator_id,
                tenant_id=self.tenant_id,
                required_permission=required_permission,
                resource_tenant_id=resource_tenant_id,
            )
        except (PermissionError, SecurityError):
            # Auditoria de acesso negado já foi feita pelo RBAC
            raise

    def _validate_tenant_access(self, resource_tenant_id: str) -> None:
        """
        Valida se operador está acessando recurso do próprio tenant.

        Args:
            resource_tenant_id: ID do tenant do recurso

        Raises:
            SecurityError: Se IDOR detectado
        """
        if resource_tenant_id != self.tenant_id:
            # Verifica se é SUPER_ADMIN (pode acessar qualquer tenant)
            perms = self.rbac.get_operator_permissions(self.operator_id, self.tenant_id)

            if Permission.MANAGE_TENANTS not in perms:
                raise SecurityError(
                    f"IDOR: Operador {self.operator_id} do tenant {self.tenant_id} "
                    f"tentou acessar recurso do tenant {resource_tenant_id}"
                )

    def _log_audit(
        self,
        action: AuditAction,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        description: str = "",
        success: bool = True,
        severity: AuditSeverity = AuditSeverity.INFO,
        error_message: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Registra evento de auditoria.

        Args:
            action: Ação realizada
            resource: Tipo de recurso
            resource_id: ID do recurso
            description: Descrição do evento
            success: Se operação foi bem-sucedida
            severity: Severidade
            error_message: Mensagem de erro (se falhou)
            metadata: Metadados adicionais
        """
        self.audit.log(
            tenant_id=self.tenant_id,
            operator_id=self.operator_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            description=description,
            success=success,
            severity=severity,
            metadata=metadata or {},
            session_id=self.session_id,
            ip_address=self.ip_address,
            error_message=error_message,
        )

    def _graceful_shutdown(self, action: AuditAction, reason: str) -> None:
        """
        Graceful shutdown em caso de anomalia de segurança.

        Args:
            action: Ação que causou shutdown
            reason: Motivo do shutdown
        """
        logger.critical(
            f"🚨 GRACEFUL SHUTDOWN | Ação: {action.value} | Motivo: {reason}"
        )

        # Auditoria crítica
        self._log_audit(
            action=action,
            description=f"SHUTDOWN: {reason}",
            success=False,
            severity=AuditSeverity.CRITICAL,
        )

        # Em produção, aqui você:
        # - Notificaria equipe de segurança
        # - Bloquearia temporariamente o operador
        # - Dispararia webhook para SIEM

    def get_security_status(self) -> Dict[str, Any]:
        """
        Retorna status de segurança do serviço.

        Returns:
            Dict com métricas de segurança
        """
        return {
            "tenant_id": self.tenant_id,
            "operator_id": self.operator_id,
            "vault": self.vault.get_health_status(),
            "rbac": self.rbac.get_security_stats(),
            "pii": self.pii.get_pii_stats(self.tenant_id),
            "audit": self.audit.verify_log_integrity(self.tenant_id),
        }
