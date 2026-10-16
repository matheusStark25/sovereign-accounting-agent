"""Key Vault Service: gerencia chaves AES-256-GCM e rotação.

Usa DatabaseService to persist encrypted keys via SecretManager.
"""

from __future__ import annotations

import os
import time
import base64
import logging
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from contabil_agente.services.secret_manager import SecretManager
from contabil_agente.services.database_service import DatabaseService

logger = logging.getLogger("key_vault_service")


class KeyVaultService:
    def __init__(self):
        self.secrets = SecretManager()
        self.db = DatabaseService()
        # load master key from secret manager or env
        mk = os.getenv("STARK_MASTER_KEY") or self.secrets.get("STARK_MASTER_KEY")
        if mk:
            # derive key bytes
            self.master = mk.encode()
        else:
            self.master = None

    def generate_data_key(self) -> bytes:
        key = AESGCM.generate_key(bit_length=256)
        return key

    def encrypt_with_data_key(self, data_key: bytes, plaintext: bytes) -> str:
        nonce = os.urandom(12)
        aead = AESGCM(data_key)
        ct = aead.encrypt(nonce, plaintext, None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt_with_data_key(self, data_key: bytes, token: str) -> bytes:
        blob = base64.b64decode(token)
        nonce = blob[:12]
        ct = blob[12:]
        aead = AESGCM(data_key)
        return aead.decrypt(nonce, ct, None)

    def wrap_data_key(self, data_key: bytes) -> str:
        # wrap with master key (if available) using AESGCM
        if not self.master:
            raise RuntimeError("no_master_key")
        master_aead = AESGCM(self.master[:32])
        nonce = os.urandom(12)
        ct = master_aead.encrypt(nonce, data_key, None)
        token = base64.b64encode(nonce + ct).decode()
        # persist wrapped key in secrets
        self.secrets.save("DATA_KEY_WRAPPED", token)
        return token

    def unwrap_data_key(self) -> bytes:
        token = self.secrets.get("DATA_KEY_WRAPPED")
        if not token:
            raise RuntimeError("no_wrapped_key")
        blob = base64.b64decode(token)
        nonce = blob[:12]
        ct = blob[12:]
        master_aead = AESGCM(self.master[:32])
        return master_aead.decrypt(nonce, ct, None)

    def rotate_data_key(self, new_key: Optional[bytes] = None) -> str:
        new_key = new_key or self.generate_data_key()
        token = self.wrap_data_key(new_key)
        self.db.log_audit(
            "info", "key_vault", "rotated_data_key", {"timestamp": int(time.time())}
        )
        return token


__all__ = ["KeyVaultService"]
