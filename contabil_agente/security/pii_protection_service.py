"""
PIIProtectionService - Proteção de Dados Pessoais (LGPD/GDPR)
=============================================================

Serviço de proteção de informações pessoalmente identificáveis com:
- Masking (ocultação) para visualização
- Hashing irreversível para busca
- Tokenização reversível para processamento
- Políticas de retenção de dados
- Consentimento e rastreabilidade

Princípios:
- Minimização de dados (coletar apenas o necessário)
- Anonimização quando possível
- Pseudonimização quando necessário processamento
- Auditoria de todos os acessos a PII
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PIIType(Enum):
    """Tipos de dados pessoais identificáveis."""

    CPF = "cp"
    CNPJ = "cnpj"
    EMAIL = "email"
    PHONE = "phone"
    BANK_ACCOUNT = "bank_account"
    CREDIT_CARD = "credit_card"
    RG = "rg"
    PASSPORT = "passport"
    ADDRESS = "address"
    NAME = "name"
    SALARY = "salary"


class RetentionPolicy(Enum):
    """Políticas de retenção de dados LGPD."""

    SHORT_TERM = 30  # 30 dias
    MEDIUM_TERM = 180  # 6 meses
    LONG_TERM = 1825  # 5 anos (obrigações fiscais)
    PERMANENT = -1  # Permanente (dados essenciais)


@dataclass
class PIIMetadata:
    """Metadados de um campo PII."""

    field_name: str
    pii_type: PIIType
    retention_policy: RetentionPolicy
    created_at: datetime = field(default_factory=datetime.now)
    consent_given: bool = False
    consent_date: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    expires_at: Optional[datetime] = None


class PIIProtectionService:
    """
    Serviço de proteção de dados pessoais (LGPD/GDPR).

    Features:
    - Masking para visualização segura
    - Hashing SHA-256 para busca sem expor dados
    - Tokenização para processamento reversível
    - Validação de consentimento
    - Aplicação de políticas de retenção
    """

    # Campos que contêm PII (mapeamento)
    PII_FIELDS_MAP: Dict[str, PIIType] = {
        "cp": PIIType.CPF,
        "cnpj": PIIType.CNPJ,
        "email": PIIType.EMAIL,
        "telefone": PIIType.PHONE,
        "phone": PIIType.PHONE,
        "conta_bancaria": PIIType.BANK_ACCOUNT,
        "bank_account": PIIType.BANK_ACCOUNT,
        "cartao_credito": PIIType.CREDIT_CARD,
        "rg": PIIType.RG,
        "passaporte": PIIType.PASSPORT,
        "endereco": PIIType.ADDRESS,
        "address": PIIType.ADDRESS,
        "nome": PIIType.NAME,
        "name": PIIType.NAME,
        "salario": PIIType.SALARY,
        "salary": PIIType.SALARY,
    }

    # Políticas de retenção por tipo de dado
    DEFAULT_RETENTION: Dict[PIIType, RetentionPolicy] = {
        PIIType.CPF: RetentionPolicy.LONG_TERM,
        PIIType.CNPJ: RetentionPolicy.LONG_TERM,
        PIIType.EMAIL: RetentionPolicy.MEDIUM_TERM,
        PIIType.PHONE: RetentionPolicy.MEDIUM_TERM,
        PIIType.SALARY: RetentionPolicy.LONG_TERM,
        PIIType.ADDRESS: RetentionPolicy.MEDIUM_TERM,
    }

    def __init__(self):
        """Inicializa o serviço de proteção PII."""
        self._pii_metadata: Dict[str, PIIMetadata] = {}
        logger.info("PIIProtectionService inicializado (LGPD/GDPR)")

    def mask(
        self, value: str, pii_type: Optional[PIIType] = None, reveal_chars: int = 3
    ) -> str:
        """
        Mascara dados pessoais para visualização.

        Args:
            value: Valor a mascarar
            pii_type: Tipo de dado (auto-detecta se None)
            reveal_chars: Quantos caracteres revelar no início/fim

        Returns:
            Valor mascarado

        Examples:
            >>> mask("12345678901", PIIType.CPF)
            "123.***.***-01"

            >>> mask("joao@email.com", PIIType.EMAIL)
            "joa***@email.com"
        """
        if not value:
            return ""

        # Auto-detecta tipo se não fornecido
        if pii_type is None:
            pii_type = self._detect_pii_type(value)

        # Aplica masking específico por tipo
        if pii_type == PIIType.CPF:
            return self._mask_cpf(value)
        elif pii_type == PIIType.CNPJ:
            return self._mask_cnpj(value)
        elif pii_type == PIIType.EMAIL:
            return self._mask_email(value)
        elif pii_type == PIIType.PHONE:
            return self._mask_phone(value)
        elif pii_type == PIIType.CREDIT_CARD:
            return self._mask_credit_card(value)
        elif pii_type == PIIType.SALARY:
            return "R$ [CONFIDENCIAL]"
        else:
            # Masking genérico
            return self._mask_generic(value, reveal_chars)

    def _mask_cpf(self, cpf: str) -> str:
        """Mascara CPF: 123.456.789-01 → 123.***.***-01"""
        cpf_clean = re.sub(r"\D", "", cpf)
        if len(cpf_clean) == 11:
            return f"{cpf_clean[:3]}.***.***-{cpf_clean[-2:]}"
        return "***.***.***-**"

    def _mask_cnpj(self, cnpj: str) -> str:
        """Mascara CNPJ: 12.345.678/0001-99 → 12.***.****/****-99"""
        cnpj_clean = re.sub(r"\D", "", cnpj)
        if len(cnpj_clean) == 14:
            return f"{cnpj_clean[:2]}.***.***/****-{cnpj_clean[-2:]}"
        return "**.***.****/****-**"

    def _mask_email(self, email: str) -> str:
        """Mascara email: joao.silva@email.com → joa***@email.com"""
        if "@" not in email:
            return "***@***.***"
        local, domain = email.split("@", 1)
        masked_local = local[:3] + "***" if len(local) > 3 else "***"
        return f"{masked_local}@{domain}"

    def _mask_phone(self, phone: str) -> str:
        """Mascara telefone: (11) 98765-4321 → (11) 9****-**21"""
        phone_clean = re.sub(r"\D", "", phone)
        if len(phone_clean) >= 10:
            return f"({phone_clean[:2]}) *****-**{phone_clean[-2:]}"
        return "(**) *****-****"

    def _mask_credit_card(self, card: str) -> str:
        """Mascara cartão: 1234 5678 9012 3456 → **** **** **** 3456"""
        card_clean = re.sub(r"\D", "", card)
        return (
            f"**** **** **** {card_clean[-4:]}"
            if len(card_clean) >= 13
            else "**** **** **** ****"
        )

    def _mask_generic(self, value: str, reveal_chars: int) -> str:
        """Masking genérico."""
        if len(value) <= reveal_chars * 2:
            return "*" * len(value)
        start = value[:reveal_chars]
        end = value[-reveal_chars:]
        return f"{start}{'*' * (len(value) - reveal_chars * 2)}{end}"

    def hash_for_search(
        self, value: str, pii_type: Optional[PIIType] = None, salt: str = ""
    ) -> str:
        """
        Hash SHA-256 de dados PII para busca sem expor valor real.

        Args:
            value: Valor a fazer hash
            pii_type: Tipo de dado
            salt: Salt adicional (opcional)

        Returns:
            Hash hexadecimal

        Uso:
            Ao invés de buscar WHERE cpf = '12345678901',
            buscar WHERE cpf_hash = hash_for_search('12345678901')
        """
        # Normaliza valor (remove formatação)
        normalized = self._normalize_value(value, pii_type)

        # Adiciona salt se fornecido
        to_hash = f"{normalized}{salt}".encode("utf-8")

        # SHA-256 (irreversível)
        return hashlib.sha256(to_hash).hexdigest()

    def _normalize_value(self, value: str, pii_type: Optional[PIIType]) -> str:
        """Normaliza valor removendo formatação."""
        if pii_type in [PIIType.CPF, PIIType.CNPJ, PIIType.PHONE]:
            # Remove tudo exceto dígitos
            return re.sub(r"\D", "", value)
        elif pii_type == PIIType.EMAIL:
            # Lowercase
            return value.lower().strip()
        else:
            # Remove espaços extras
            return value.strip()

    def _detect_pii_type(self, value: str) -> Optional[PIIType]:
        """Auto-detecta tipo de PII baseado no formato."""
        # Remove formatação
        clean = re.sub(r"\D", "", value)

        # CPF: 11 dígitos
        if len(clean) == 11:
            return PIIType.CPF

        # CNPJ: 14 dígitos
        if len(clean) == 14:
            return PIIType.CNPJ

        # Email
        if "@" in value and "." in value:
            return PIIType.EMAIL

        # Telefone: 10-11 dígitos
        if len(clean) in [10, 11]:
            return PIIType.PHONE

        return None

    def apply_pii_masking(
        self, data: Dict[str, Any], fields_to_mask: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Aplica masking em campos específicos de um dict.

        Args:
            data: Dicionário com dados
            fields_to_mask: Lista de campos a mascarar (None = auto-detecta)

        Returns:
            Dicionário com campos mascarados
        """
        masked_data = data.copy()

        # Auto-detecta campos PII se não especificado
        if fields_to_mask is None:
            fields_to_mask = [
                key for key in data.keys() if key.lower() in self.PII_FIELDS_MAP
            ]

        for field_item in fields_to_mask:
            if field_item in masked_data and masked_data[field_item]:
                value = str(masked_data[field_item])

                # Determina tipo de PII
                pii_type = self.PII_FIELDS_MAP.get(field_item.lower())

                # Aplica masking
                masked_data[field_item] = self.mask(value, pii_type)

        return masked_data

    def validate_consent(self, field_name: str, tenant_id: str, purpose: str) -> bool:
        """
        Valida se há consentimento para usar dados PII (LGPD Art. 7).

        Args:
            field_name: Nome do campo
            tenant_id: ID do tenant
            purpose: Finalidade do uso

        Returns:
            True se consentimento válido
        """
        metadata_key = f"{tenant_id}:{field_name}"
        metadata = self._pii_metadata.get(metadata_key)

        if not metadata:
            logger.warning(f"Sem metadados PII para {field_name} (tenant: {tenant_id})")
            return False

        if not metadata.consent_given:
            logger.warning(f"Sem consentimento para {field_name} (tenant: {tenant_id})")
            return False

        # Valida se ainda dentro do prazo de consentimento
        if metadata.expires_at and datetime.now() > metadata.expires_at:
            logger.warning(
                f"Consentimento expirado para {field_name} (tenant: {tenant_id})"
            )
            return False

        # Registra acesso
        metadata.last_accessed = datetime.now()
        metadata.access_count += 1

        logger.info(f"Acesso a PII autorizado: {field_name} (finalidade: {purpose})")
        return True

    def register_consent(
        self,
        field_name: str,
        tenant_id: str,
        pii_type: PIIType,
        retention_policy: Optional[RetentionPolicy] = None,
    ) -> PIIMetadata:
        """
        Registra consentimento para coleta de dados (LGPD Art. 8).

        Args:
            field_name: Nome do campo
            tenant_id: ID do tenant
            pii_type: Tipo de PII
            retention_policy: Política de retenção (usa padrão se None)

        Returns:
            Metadados do campo PII
        """
        # Usa política padrão se não especificada
        if retention_policy is None:
            retention_policy = self.DEFAULT_RETENTION.get(
                pii_type, RetentionPolicy.MEDIUM_TERM
            )

        # Calcula data de expiração
        now = datetime.now()
        if retention_policy == RetentionPolicy.PERMANENT:
            expires_at = None
        else:
            expires_at = now + timedelta(days=retention_policy.value)

        # Cria metadados
        metadata = PIIMetadata(
            field_name=field_name,
            pii_type=pii_type,
            retention_policy=retention_policy,
            consent_given=True,
            consent_date=now,
            expires_at=expires_at,
        )

        # Armazena
        metadata_key = f"{tenant_id}:{field_name}"
        self._pii_metadata[metadata_key] = metadata

        logger.info(
            f"Consentimento registrado: {field_name} @ {tenant_id} "
            f"(retenção: {retention_policy.name}, expira: {expires_at})"
        )

        return metadata

    def check_retention_policy(self, tenant_id: str) -> List[str]:
        """
        Verifica campos que devem ser excluídos por política de retenção.

        Args:
            tenant_id: ID do tenant

        Returns:
            Lista de campos a excluir
        """
        to_delete = []
        now = datetime.now()

        for key, metadata in self._pii_metadata.items():
            if not key.startswith(f"{tenant_id}:"):
                continue

            # Verifica se expirou
            if metadata.expires_at and now > metadata.expires_at:
                to_delete.append(metadata.field_name)
                logger.warning(
                    f"Campo PII expirado: {metadata.field_name} "
                    f"(expirou em {metadata.expires_at})"
                )

        return to_delete

    def anonymize_field(self, value: str, pii_type: PIIType) -> str:
        """
        Anonimiza completamente um campo (irreversível).

        Args:
            value: Valor a anonimizar
            pii_type: Tipo de PII

        Returns:
            Valor anonimizado
        """
        # Hash com salt aleatório (impossível reverter)
        import secrets

        salt = secrets.token_hex(16)
        hashed = self.hash_for_search(value, pii_type, salt)
        return f"ANON:{hashed[:16]}"

    def get_pii_stats(self, tenant_id: str) -> Dict:
        """
        Retorna estatísticas de PII para um tenant.

        Args:
            tenant_id: ID do tenant

        Returns:
            Dict com estatísticas
        """
        tenant_pii = [
            m for k, m in self._pii_metadata.items() if k.startswith(f"{tenant_id}:")
        ]

        total = len(tenant_pii)
        with_consent = sum(1 for m in tenant_pii if m.consent_given)
        expired = sum(
            1 for m in tenant_pii if m.expires_at and datetime.now() > m.expires_at
        )

        return {
            "total_pii_fields": total,
            "with_consent": with_consent,
            "without_consent": total - with_consent,
            "expired": expired,
            "retention_policies": {
                policy.name: sum(1 for m in tenant_pii if m.retention_policy == policy)
                for policy in RetentionPolicy
            },
        }

    # Compatibility wrappers (old API expected these names)
    def mask_field(
        self, value: str, pii_type: Optional[PIIType] = None, reveal_chars: int = 3
    ) -> str:
        """Backward-compatible alias for `mask` used in tests."""
        return self.mask(value, pii_type, reveal_chars)

    def hash_pii_field(self, value: str, pii_type: Optional[PIIType] = None) -> str:
        """Backward-compatible alias for `hash_for_search` used in tests."""
        return self.hash_for_search(value, pii_type)
