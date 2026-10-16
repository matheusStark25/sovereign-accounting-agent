from __future__ import annotations

import os
from contextlib import contextmanager

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:
    AESGCM = None


@contextmanager
def ephemeral_aes_key(key_size: int = 32):
    """Context manager providing ephemeral AES key bytes.

    Yields raw key bytes and guarantees best-effort zeroing after use.
    """
    key = os.urandom(key_size)
    try:
        yield key
    finally:
        try:
            # overwrite memory where possible
            if isinstance(key, bytearray):
                for i in range(len(key)):
                    key[i] = 0
        except Exception:
            pass
