"""
VaultManager - Gestão de Secrets e Rotação de Chaves
====================================================

Gerenciador centralizado de secrets com:
- Zero hardcoding de credenciais
- Rotação de chaves sem downtime
- Versioning de chaves
- Caching seguro em memória
- Fail-safe em caso de ausência de secrets

Princípios:
- Nunca expor chaves em logs
- Sempre validar presença de secrets
- Suportar múltiplas versões de chaves simultaneamente
"""

import logging
import os
from datetime import datetime
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VaultManager:
    """
    Gerenciador de Secrets com rotação de chaves e versioning.

    Features:
    - Carregamento de secrets via variáveis de ambiente
    - Suporte a múltiplas versões de chaves (key rotation)
    - Cache thread-safe em memória
    - Validação de integridade de secrets
    """

    _instance = None
    _lock = Lock()

    # Configurações de rotação
    KEY_ROTATION_DAYS = 90
    CACHE_TTL_SECONDS = 3600

    def __new__(cls):
        """Singleton pattern para garantir única instância."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Inicializa o gerenciador de secrets."""
        if not hasattr(self, "_initialized"):
            self._secrets_cache: Dict[str, Any] = {}
            self._cache_timestamps: Dict[str, datetime] = {}
            self._key_versions: Dict[str, int] = {}
            self._initialized = True
            self._load_secrets()
            logger.info("VaultManager inicializado com sucesso")

    def _load_secrets(self) -> None:
        """Carrega secrets das variáveis de ambiente."""
        try:
            # Chaves de criptografia (suporta múltiplas versões)
            self._load_encryption_keys()

            # Chaves HMAC para assinatura de audit logs
            self._load_hmac_keys()

            # Credenciais de banco de dados
            self._load_database_credentials()

            # API Keys externas
            self._load_api_keys()

            logger.info("Secrets carregados com sucesso")

        except Exception as e:
            logger.critical(f"FALHA CRÍTICA ao carregar secrets: {e}")
            raise RuntimeError("Sistema não pode iniciar sem secrets configurados")

    def _load_encryption_keys(self) -> None:
        """Carrega chaves de criptografia com suporte a rotação."""
        # Chave atual (obrigatória)
        current_key = os.getenv("ENCRYPTION_KEY_CURRENT")
        if not current_key or len(current_key) < 32:
            raise ValueError(
                "ENCRYPTION_KEY_CURRENT não encontrada ou muito curta (mínimo 32 chars). "
                'Execute: python -c "import secrets; print(secrets.token_hex(32))"'
            )

        self._secrets_cache["encryption_key_current"] = current_key
        self._key_versions["encryption"] = int(os.getenv("ENCRYPTION_KEY_VERSION", "1"))

        # Chaves antigas para descriptografar dados legados
        for i in range(1, 5):  # Suporta até 4 chaves antigas
            old_key = os.getenv(f"ENCRYPTION_KEY_V{i}")
            if old_key:
                self._secrets_cache[f"encryption_key_v{i}"] = old_key
                logger.info(f"Chave de criptografia v{i} carregada (rotação)")

    def _load_hmac_keys(self) -> None:
        """Carrega chaves HMAC para assinatura de logs de auditoria."""
        hmac_key = os.getenv("HMAC_SECRET_KEY")
        if not hmac_key or len(hmac_key) < 32:
            # Gera chave temporária com warning severo
            logger.error(
                "HMAC_SECRET_KEY não configurada! Gerando chave temporária. "
                "AUDIT LOGS NÃO SERÃO VÁLIDOS APÓS RESTART!"
            )
            import secrets

            hmac_key = secrets.token_hex(32)

        self._secrets_cache["hmac_key_current"] = hmac_key
        self._key_versions["hmac"] = int(os.getenv("HMAC_KEY_VERSION", "1"))

    def _load_database_credentials(self) -> None:
        """Carrega credenciais de banco de dados."""
        db_password = os.getenv("DB_PASSWORD")
        if db_password:
            self._secrets_cache["db_password"] = db_password

        # Suporte a múltiplos bancos (multi-tenant)
        for tenant_id in ["TENANT_MASTER", "TENANT_BACKUP"]:
            tenant_pwd = os.getenv(f"DB_PASSWORD_{tenant_id}")
            if tenant_pwd:
                self._secrets_cache[f"db_password_{tenant_id.lower()}"] = tenant_pwd

    def _load_api_keys(self) -> None:
        """Carrega API keys de serviços externos."""
        api_keys = {
            "aws_secret_key": "AWS_SECRET_ACCESS_KEY",
            "azure_key": "AZURE_KEY",
            "openai_key": "OPENAI_API_KEY",
            "groq_key": "GROQ_API_KEY",
        }

        for key_name, env_var in api_keys.items():
            value = os.getenv(env_var)
            if value:
                self._secrets_cache[key_name] = value

    def get_secret(self, key: str, use_cache: bool = True) -> Optional[str]:
        """
        Recupera um secret do cache/ambiente.

        Args:
            key: Nome do secret
            use_cache: Se False, força reload do ambiente

        Returns:
            Valor do secret ou None se não encontrado
        """
        try:
            # Validar cache
            if use_cache and key in self._secrets_cache:
                if self._is_cache_valid(key):
                    return self._secrets_cache[key]

            # Reload se cache expirado
            value = os.getenv(key.upper())
            if value:
                self._secrets_cache[key] = value
                self._cache_timestamps[key] = datetime.now()

            return value

        except Exception as e:
            logger.error(f"Erro ao recuperar secret '{key}': {e}")
            return None

    def _ensure_initialized(self) -> None:
        """Ensure the instance has been initialized (defensive for singleton)."""
        if not hasattr(self, "_initialized") or not getattr(self, "_initialized"):
            # Try initializing attributes and loading secrets
            try:
                self._secrets_cache = getattr(self, "_secrets_cache", {})
                self._cache_timestamps = getattr(self, "_cache_timestamps", {})
                self._key_versions = getattr(self, "_key_versions", {})
                self._initialized = True
                # Attempt to load secrets if cache is empty
                if not self._secrets_cache:
                    self._load_secrets()
            except Exception:
                # best-effort - don't crash here
                pass

    def get_encryption_key(self, version: Optional[int] = None) -> str:
        """
        Retorna chave de criptografia (atual ou versão específica).

        Args:
            version: Versão da chave (None = atual)

        Returns:
            Chave de criptografia

        Raises:
            ValueError: Se chave não encontrada
        """
        # Defensive init
        self._ensure_initialized()

        if version is None:
            key = self._secrets_cache.get("encryption_key_current")
        else:
            # Se a versão solicitada é a versão atual, retorna a chave atual
            current_version = self._key_versions.get("encryption", 1)
            if version == current_version:
                key = self._secrets_cache.get("encryption_key_current")
            else:
                key = self._secrets_cache.get(f"encryption_key_v{version}")

        if not key:
            raise ValueError(f"Chave de criptografia v{version} não encontrada")

        return key

    def get_hmac_key(self) -> str:
        """
        Retorna chave HMAC para assinatura de audit logs.

        Returns:
            Chave HMAC

        Raises:
            ValueError: Se chave não encontrada
        """
        self._ensure_initialized()

        key = self._secrets_cache.get("hmac_key_current")
        if not key:
            raise ValueError("Chave HMAC não configurada")
        return key

    def get_key_version(self, key_type: str) -> int:
        """Retorna versão atual de uma chave."""
        self._ensure_initialized()
        return self._key_versions.get(key_type, 1)

    def rotate_key(self, key_type: str, new_key: str) -> None:
        """
        Rotaciona uma chave (encryption ou hmac).

        Args:
            key_type: Tipo de chave ('encryption' ou 'hmac')
            new_key: Nova chave a ser usada

        Process:
            1. Move chave atual para versão antiga
            2. Define nova chave como atual
            3. Incrementa versão
        """
        try:
            current_version = self._key_versions.get(key_type, 1)

            # Backup da chave atual
            if key_type == "encryption":
                old_key = self._secrets_cache.get("encryption_key_current")
                if old_key:
                    self._secrets_cache[f"encryption_key_v{current_version}"] = old_key
                self._secrets_cache["encryption_key_current"] = new_key

            elif key_type == "hmac":
                old_key = self._secrets_cache.get("hmac_key_current")
                if old_key:
                    self._secrets_cache[f"hmac_key_v{current_version}"] = old_key
                self._secrets_cache["hmac_key_current"] = new_key

            # Incrementa versão
            self._key_versions[key_type] = current_version + 1

            logger.warning(
                f"Chave {key_type} rotacionada: v{current_version} → v{current_version + 1}"
            )

        except Exception as e:
            logger.critical(f"FALHA na rotação de chave {key_type}: {e}")
            raise

    def _is_cache_valid(self, key: str) -> bool:
        """Verifica se cache de um secret ainda é válido."""
        if key not in self._cache_timestamps:
            return False

        timestamp = self._cache_timestamps[key]
        age = (datetime.now() - timestamp).total_seconds()
        return age < self.CACHE_TTL_SECONDS

    def clear_cache(self) -> None:
        """Limpa cache de secrets (força reload)."""
        with self._lock:
            self._secrets_cache.clear()
            self._cache_timestamps.clear()
            self._load_secrets()
            logger.info("Cache de secrets limpo e recarregado")

    def get_health_status(self) -> Dict[str, Any]:
        """
        Retorna status de saúde do VaultManager.

        Returns:
            Dict com métricas de saúde
        """
        return {
            "status": "healthy",
            "secrets_loaded": len(self._secrets_cache),
            "encryption_key_version": self._key_versions.get("encryption", 1),
            "hmac_key_version": self._key_versions.get("hmac", 1),
            "cache_size_mb": self._get_cache_size_mb(),
            "oldest_cache_age_seconds": self._get_oldest_cache_age(),
        }

    # Backwards-compatible alias expected by some tests
    def health_check(self) -> Dict[str, Any]:
        return self.get_health_status()

    def _get_cache_size_mb(self) -> float:
        """Estima tamanho do cache em MB."""
        import sys

        total_size = sum(sys.getsizeof(v) for v in self._secrets_cache.values())
        return round(total_size / (1024 * 1024), 3)

    def _get_oldest_cache_age(self) -> int:
        """Retorna idade do cache mais antigo em segundos."""
        if not self._cache_timestamps:
            return 0
        oldest = min(self._cache_timestamps.values())
        return int((datetime.now() - oldest).total_seconds())

    def validate_secrets(self) -> bool:
        """
        Valida se todos os secrets críticos estão presentes.

        Returns:
            True se todos os secrets críticos estão ok
        """
        required_secrets = [
            "encryption_key_current",
            "hmac_key_current",
        ]

        for secret in required_secrets:
            if secret not in self._secrets_cache:
                logger.error(f"Secret crítico ausente: {secret}")
                return False

        logger.info("Validação de secrets: ✓ OK")
        return True
