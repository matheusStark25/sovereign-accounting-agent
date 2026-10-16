import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # dotenv optional; environment variables still work
    pass

# optional encryption
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    HAS_AESGCM = True
except Exception:
    AESGCM = None
    HAS_AESGCM = False
try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None

try:
    from contabil_agente.services.database_service import DatabaseService
except Exception:
    DatabaseService = None


class SecretManager:
    """Simple secrets loader following ENV > defaults. No hardcoding.

    Uses os.environ, with optional .env support when python-dotenv is installed.
    """

    def __init__(self, namespace: Optional[str] = None):
        self.namespace = (namespace + "_") if namespace else ""
        # Prefer AES-GCM with master key `STARK_MASTER_KEY` (32 bytes raw or base64); fall back to Fernet
        self._aead = None
        master = os.getenv("STARK_MASTER_KEY")
        if master and HAS_AESGCM:
            try:
                # derive 32-byte key via HKDF if master is longer
                mk = master.encode()
                hkdf = HKDF(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=None,
                    info=b"stark_master_key",
                )
                key = hkdf.derive(mk)
                self._aead = AESGCM(key)
            except Exception:
                self._aead = None

        if not self._aead:
            key = os.getenv("SECRET_FERNET_KEY")
            self._fernet = Fernet(key) if key and Fernet else None
        else:
            self._fernet = None
        self._db = DatabaseService() if DatabaseService else None

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        name = f"{self.namespace}{key}"
        # Priority: ENV -> DB encrypted -> default
        val = os.getenv(name)
        if val is not None:
            # if stored encrypted marker
            if val.startswith("ENC:") and self._fernet:
                try:
                    return self._fernet.decrypt(val[4:].encode()).decode()
                except Exception:
                    return default
            return val

        # try DB
        try:
            if self._db:
                stored = self._db.get_secret(name)
                if stored:
                    if stored.startswith("ENC:"):
                        token = stored[4:]
                        # try AESGCM unwrap
                        if self._aead:
                            try:
                                import base64

                                blob = base64.b64decode(token)
                                # first 12 bytes nonce
                                nonce = blob[:12]
                                ct = blob[12:]
                                plain = self._aead.decrypt(nonce, ct, None)
                                return plain.decode()
                            except Exception:
                                pass
                        if self._fernet:
                            try:
                                return self._fernet.decrypt(token.encode()).decode()
                            except Exception:
                                return default
                    return stored
        except Exception:
            pass

        return default

    def save(self, key: str, value: str) -> None:
        name = f"{self.namespace}{key}"
        to_store = value
        # Prefer AESGCM envelope
        if getattr(self, "_aead", None):
            try:
                import base64

                nonce = os.urandom(12)
                ct = self._aead.encrypt(nonce, value.encode(), None)
                token = base64.b64encode(nonce + ct).decode()
                to_store = f"ENC:{token}"
            except Exception:
                to_store = value
        elif getattr(self, "_fernet", None):
            try:
                token = self._fernet.encrypt(value.encode()).decode()
                to_store = f"ENC:{token}"
            except Exception:
                to_store = value
        # save to DB if available, otherwise warn
        if self._db:
            try:
                self._db.save_secret(name, to_store)
                return
            except Exception:
                logger.debug("failed to save secret to db")
        # fallback: set env (not persistent across restarts)
        os.environ[name] = to_store

    def require(self, key: str) -> str:
        v = self.get(key)
        if not v:
            logger.error("Missing required secret: %s", f"{self.namespace}{key}")
            raise RuntimeError(f"Missing required secret: {self.namespace}{key}")
        return v


__all__ = ["SecretManager"]
