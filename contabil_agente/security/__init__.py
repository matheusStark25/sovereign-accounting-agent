"""
Camada de Segurança & Compliance - Sistema Contábil Maria Helena
================================================================

Módulo de segurança empresarial com:
- Criptografia AES-256 em repouso e transporte
- Gestão de Secrets com rotação de chaves
- Proteção PII/LGPD com masking e hashing
- Audit Trail imutável com assinatura HMAC
- Multi-tenant com RBAC de elite
- Defesa em profundidade

Autor: Sistema Contábil Maria Helena
Data: 2026-02-03
"""

from .accounting_service import SecureAccountingService
from .audit_trail_manager import AuditAction, AuditTrailManager
from .encryption_service import EncryptionService
from .pii_protection_service import PIIProtectionService, PIIType
from .rbac_manager import Permission, RBACManager, Role
from .vault_manager import VaultManager

__all__ = [
    "VaultManager",
    "EncryptionService",
    "RBACManager",
    "Role",
    "Permission",
    "PIIProtectionService",
    "PIIType",
    "AuditTrailManager",
    "AuditAction",
    "SecureAccountingService",
]

__version__ = "1.0.0"
