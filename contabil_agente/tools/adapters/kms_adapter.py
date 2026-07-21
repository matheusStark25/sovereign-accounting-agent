from __future__ import annotations

import hashlib


class KMSAdapter:
    """Minimal KMS/HSM adapter stub.

    In production this should wrap an HSM or cloud KMS (FIPS 140-2 L3).
    """

    def __init__(self, *, algorithm: str = "RSA-4096", key_version: str = "2026Q1"):
        self.algorithm = algorithm
        self.key_version = key_version
        # public_key_bytes stored for fingerprinting; in real system load from KMS
        self.public_key_bytes = hashlib.sha256(b"dummy_public").digest()

    def sign(self, data: bytes) -> bytes:
        # Replace with KMS sign call. Local stub: HMAC-like deterministic signature.
        return hashlib.sha256(b"kms-sign:" + data).digest()

    def rotate_key(self) -> None:
        # Key rotation scaffold
        self.key_version = (
            str(int(self.key_version) + 1)
            if self.key_version.isdigit()
            else self.key_version
        )
