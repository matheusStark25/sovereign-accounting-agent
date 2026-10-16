"""AuditTrailManager: interface de auditoria do sistema, gravada na trilha WORM encadeada.

Cada evento vira uma entrada de ``WormAudit`` (HMAC-SHA256 encadeado, uma trilha por tenant). Falha
ao gravar levanta ``AuditoriaError``: auditoria que falha em silêncio não é auditoria.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .worm_audit import AuditoriaError, WormAudit

logger = logging.getLogger(__name__)


class AuditAction(Enum):
    """Ações auditáveis do sistema."""

    LOGIN = "login"
    LOGOUT = "logout"
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    PERMISSION_CHECK = "permission_check"

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    READ_DATA = READ
    WRITE_DATA = CREATE

    PROCESS_PAYROLL = "process_payroll"
    PROCESS_DOCUMENT = "process_document"
    GENERATE_SPED = "generate_sped"
    SIGN_DOCUMENT = "sign_document"

    KEY_ROTATION = "key_rotation"
    ENCRYPTION = "encryption"
    DECRYPTION = "decryption"
    PII_ACCESS = "pii_access"

    USER_CREATED = "user_created"
    USER_DEACTIVATED = "user_deactivated"
    CONFIG_CHANGED = "config_changed"
    DATA_ERASURE = "data_erasure"
    CONSENT_CHANGED = "consent_changed"


class AuditSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class AuditEntry:
    tenant_id: str
    operator_id: str
    session_id: Optional[str] = None
    action: AuditAction = AuditAction.READ
    severity: AuditSeverity = AuditSeverity.INFO
    resource: Optional[str] = None
    resource_id: Optional[str] = None
    description: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    signature: Optional[str] = None  # hash HMAC da entrada na cadeia


class AuditTrailManager:
    DIRETORIO_PADRAO = "logs/audit"

    def __init__(self, vault_manager: Any = None, base_directory: Optional[str] = None, worm: Optional[WormAudit] = None):
        if worm is None:
            diretorio = Path(base_directory or self.DIRETORIO_PADRAO)
            if vault_manager is not None and hasattr(vault_manager, "get_hmac_key"):
                worm = WormAudit(diretorio, vault_manager.get_hmac_key())
            else:
                worm = WormAudit.do_ambiente(diretorio)
        self.worm = worm

    # ------------------------------------------------------------------ escrita
    def log(
        self,
        tenant_id: str,
        operator_id: str,
        action: AuditAction,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        description: str = "",
        success: bool = True,
        severity: AuditSeverity = AuditSeverity.INFO,
        metadata: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> str:
        """Grava o evento e devolve o id do recibo (``tenant:seq:hash``). Levanta ``AuditoriaError`` se falhar."""
        dados = {
            "action": action.value,
            "severity": severity.value,
            "resource": resource,
            "resource_id": resource_id,
            "description": description,
            "success": success,
            "metadata": metadata or {},
        }
        for chave in ("ip_address", "user_agent", "session_id", "error_message"):
            if extra.get(chave) is not None:
                dados[chave] = extra[chave]
        return self.worm.append(action.value, dados, tenant=tenant_id, ator=operator_id).id

    # ------------------------------------------------------------------- leitura
    @staticmethod
    def _para_entrada(e: Dict[str, Any]) -> AuditEntry:
        d = e["dados"]
        return AuditEntry(
            tenant_id=e["tenant"],
            operator_id=e["ator"],
            session_id=d.get("session_id"),
            action=AuditAction(d["action"]),
            severity=AuditSeverity(d["severity"]),
            resource=d.get("resource"),
            resource_id=d.get("resource_id"),
            description=d.get("description", ""),
            timestamp=datetime.fromisoformat(e["ts"].replace("Z", "+00:00")),
            ip_address=d.get("ip_address"),
            user_agent=d.get("user_agent"),
            success=d.get("success", True),
            error_message=d.get("error_message"),
            metadata=d.get("metadata", {}),
            signature=e["hash"],
        )

    def read_audit_log(self, tenant_id: str, date: Optional[datetime | Date] = None, limit: int = 1000) -> List[AuditEntry]:
        entradas = [self._para_entrada(e) for e in self.worm.ler(tenant_id, limite=10**9)]
        if date is not None:
            alvo = date.date() if isinstance(date, datetime) else date
            entradas = [e for e in entradas if e.timestamp.date() == alvo]
        return entradas[:limit]

    def verify_log_integrity(self, tenant_id: str, date: Optional[datetime | Date] = None) -> Dict[str, Any]:
        """Verifica a trilha inteira do tenant (a cadeia não pode ser conferida por dia)."""
        v = self.worm.verificar(tenant_id)
        return {
            "tenant_id": tenant_id,
            "total_entries": v.entradas,
            "valid_signatures": v.entradas if v.ok else 0,
            "invalid_signatures": len(v.problemas),
            "integrity_ok": v.ok,
            "problemas": v.problemas,
        }

    def search_audit_log(
        self,
        tenant_id: str,
        operator_id: Optional[str] = None,
        action: Optional[AuditAction] = None,
        resource: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[AuditEntry]:
        achadas: List[AuditEntry] = []
        for entry in self.read_audit_log(tenant_id, limit=10**9):
            if operator_id and entry.operator_id != operator_id:
                continue
            if action and entry.action != action:
                continue
            if resource and entry.resource != resource:
                continue
            if start_date and entry.timestamp < start_date:
                continue
            if end_date and entry.timestamp > end_date:
                continue
            achadas.append(entry)
        return achadas[:limit]


__all__ = ["AuditAction", "AuditSeverity", "AuditEntry", "AuditTrailManager", "AuditoriaError"]
