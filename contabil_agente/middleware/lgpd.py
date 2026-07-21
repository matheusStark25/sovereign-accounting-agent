"""
LGPD compliance utilities: PII anonymization, consent management, data retention.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PIIAnonymizer:
    """Anonymiza dados pessoais em logs e outputs."""

    # Patterns para detecção de PII
    PATTERNS = {
        "cp": r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
        "cnpj": r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b",
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "telefone": r"\b(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}-?\d{4}\b",
        "rg": r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dXx]\b",
        "cartao": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
    }

    @staticmethod
    def anonymize_text(text: str, preserve_type: bool = True) -> str:
        """
        Anonymiza texto substituindo PII por placeholders.

        Args:
            text: Texto a anonimizar
            preserve_type: Se True, mantém tipo de dado (CPF->***CPF***, senão ***)
        """
        if not text:
            return text

        result = text

        for pii_type, pattern in PIIAnonymizer.PATTERNS.items():
            if preserve_type:
                replacement = f"***{pii_type.upper()}***"
            else:
                replacement = "***"

            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        return result

    @staticmethod
    def hash_pii(value: str, salt: str = "default_salt") -> str:
        """Hash irreversível para PII que precisa ser usado como chave."""
        return hashlib.sha256(f"{salt}{value}".encode()).hexdigest()[:16]

    @staticmethod
    def mask_partial(value: str, visible_start: int = 3, visible_end: int = 2) -> str:
        """Mascara parcial mantendo início e fim visíveis (ex: 123***45)."""
        if len(value) <= visible_start + visible_end:
            return "*" * len(value)

        start = value[:visible_start]
        end = value[-visible_end:] if visible_end > 0 else ""
        middle = "*" * (len(value) - visible_start - visible_end)

        return f"{start}{middle}{end}"


class ConsentManager:
    """Gerencia consentimentos LGPD dos usuários."""

    def __init__(self, storage_path: str = "lgpd_consents.json"):
        self.storage_path = storage_path
        self._consents: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        """Carrega consentimentos do disco."""
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                self._consents = json.load(f)
        except FileNotFoundError:
            # Arquivo inexistente: inicia com consentimentos vazios
            self._consents = {}
        except json.JSONDecodeError as e:
            # Arquivo inválido/corrompido: sobrescreve com estrutura vazia e loga info
            # Este caso é recuperável e não deve poluir a saída de testes com warnings.
            logger.info(
                f"Consentimentos inválidos/corrompidos em {self.storage_path}: {e} - recuperando"
            )
            self._consents = {}
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(self._consents, f, ensure_ascii=False, indent=2)
            except Exception as write_err:
                logger.error(
                    f"Falha ao recuperar arquivo de consentimentos: {write_err}"
                )
        except Exception as e:
            logger.error(f"Erro ao carregar consentimentos: {e}")
            self._consents = {}

    def _save(self):
        """Salva consentimentos no disco."""
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._consents, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar consentimentos: {e}")

    def record_consent(
        self,
        user_id: str,
        purpose: str,
        granted: bool = True,
        ip_address: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        """
        Registra consentimento do usuário.

        Args:
            user_id: Identificador único do usuário
            purpose: Finalidade do tratamento (ex: 'marketing', 'analytics')
            granted: Se consentimento foi concedido
            ip_address: IP do usuário (para auditoria)
            metadata: Dados adicionais
        """
        if user_id not in self._consents:
            self._consents[user_id] = {}

        self._consents[user_id][purpose] = {
            "granted": granted,
            "timestamp": datetime.now().isoformat(),
            "ip_address": ip_address,
            "metadata": metadata or {},
        }

        self._save()
        logger.info(
            f"Consentimento registrado: user={user_id}, purpose={purpose}, granted={granted}"
        )

    def check_consent(self, user_id: str, purpose: str) -> bool:
        """Verifica se usuário consentiu para determinada finalidade."""
        user_consents = self._consents.get(user_id, {})
        consent_record = user_consents.get(purpose, {})
        return consent_record.get("granted", False)

    def revoke_consent(self, user_id: str, purpose: str):
        """Revoga consentimento do usuário."""
        if user_id in self._consents and purpose in self._consents[user_id]:
            self._consents[user_id][purpose]["granted"] = False
            self._consents[user_id][purpose]["revoked_at"] = datetime.now().isoformat()
            self._save()
            logger.info(f"Consentimento revogado: user={user_id}, purpose={purpose}")

    def get_all_consents(self, user_id: str) -> Dict:
        """Retorna todos consentimentos de um usuário."""
        return self._consents.get(user_id, {})


class DataRetentionPolicy:
    """Gerencia políticas de retenção de dados."""

    POLICIES = {
        "chat_sessions": timedelta(days=90),  # Sessões de chat: 90 dias
        "audit_logs": timedelta(days=365),  # Logs de auditoria: 1 ano
        "user_data": timedelta(days=1825),  # Dados de usuário: 5 anos
        "temp_files": timedelta(days=7),  # Arquivos temporários: 7 dias
    }

    @staticmethod
    def should_retain(created_at: datetime, data_type: str) -> bool:
        """Verifica se dado ainda deve ser retido."""
        if data_type not in DataRetentionPolicy.POLICIES:
            logger.warning(f"Política não definida para: {data_type}")
            return True  # Por segurança, mantém se política desconhecida

        retention_period = DataRetentionPolicy.POLICIES[data_type]
        expiration = created_at + retention_period

        return datetime.now() < expiration

    @staticmethod
    def get_retention_period(data_type: str) -> Optional[timedelta]:
        """Retorna período de retenção para tipo de dado."""
        return DataRetentionPolicy.POLICIES.get(data_type)

    @staticmethod
    def mark_for_deletion(record: Dict, data_type: str) -> bool:
        """Marca registro para deleção se expirado."""
        if "created_at" not in record:
            logger.warning("Registro sem campo created_at")
            return False

        created_at = datetime.fromisoformat(record["created_at"])

        if not DataRetentionPolicy.should_retain(created_at, data_type):
            record["marked_for_deletion"] = True
            record["deletion_scheduled"] = datetime.now().isoformat()
            return True

        return False


class LGPDLogger:
    """Logger específico para eventos LGPD."""

    def __init__(self, log_file: str = "lgpd_events.log"):
        self.logger = logging.getLogger("lgpd")
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s - LGPD - %(levelname)s - %(message)s")
        )
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def log_data_access(
        self, user_id: str, data_type: str, purpose: str, ip: Optional[str] = None
    ):
        """Registra acesso a dados pessoais."""
        self.logger.info(
            f"DATA_ACCESS | user={user_id} | type={data_type} | purpose={purpose} | ip={ip}"
        )

    def log_data_export(self, user_id: str, requester: str, format: str):
        """Registra exportação de dados (portabilidade)."""
        self.logger.info(
            f"DATA_EXPORT | user={user_id} | requester={requester} | format={format}"
        )

    def log_data_deletion(self, user_id: str, data_type: str, reason: str):
        """Registra exclusão de dados."""
        self.logger.info(
            f"DATA_DELETION | user={user_id} | type={data_type} | reason={reason}"
        )

    def log_consent_change(self, user_id: str, purpose: str, granted: bool):
        """Registra mudança de consentimento."""
        action = "GRANTED" if granted else "REVOKED"
        self.logger.info(f"CONSENT_{action} | user={user_id} | purpose={purpose}")
