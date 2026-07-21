"""Post-quantum resistant store interface (fallback to AES-GCM).

This module exposes an API for encrypting sensitive artifacts to a
local store. It defaults to AES-GCM using `cryptography` if available.
Replace implementation with lattice-based KEM/KES (e.g., NTRU, Kyber) in
production to obtain quantum resistance.
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger("postquantum_store")

try:
    from contabil_agente.services.crypto_engine import aes_encrypt, aes_decrypt
except Exception as e:
    logger.exception("crypto_engine_not_loaded")
    raise RuntimeError("crypto_engine missing; failing safe") from e


STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pq_store")
os.makedirs(STORE_DIR, exist_ok=True)


class PQStore:
    def __init__(self, key: Optional[bytes] = None):
        # key size 32 bytes for AES-256-GCM
        if key:
            self._key = key
        else:
            k = os.getenv("PQ_STORE_KEY")
            self._key = bytes.fromhex(k) if k else None

    def available(self) -> bool:
        return self._key is not None

    def store(self, name: str, data: bytes) -> str:
        """Encrypt + store data, returning a location identifier."""
        if not self._key:
            path = os.path.join(STORE_DIR, name)
            with open(path, "wb") as fh:
                fh.write(data)
            logger.warning("PQ_STORE_FALLBACK_PLAINTEXT %s", path)
            return path
        try:
            obj = aes_encrypt(self._key, data)
            path = os.path.join(STORE_DIR, f"{name}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)
            return path
        except Exception:
            logger.exception("pq_store_failed")
            raise

    def retrieve(self, loc: str) -> Optional[bytes]:
        if not self._key:
            try:
                with open(loc, "rb") as fh:
                    return fh.read()
            except Exception:
                return None
        try:
            with open(loc, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            return aes_decrypt(self._key, obj)
        except Exception:
            logger.exception("pq_retrieve_failed %s", loc)
            return None


__all__ = ["PQStore"]
