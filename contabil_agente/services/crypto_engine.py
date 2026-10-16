"""Cryptographic engine using PyCryptodome: AES-256-GCM and Ed25519 signatures.

Fail-safe: if PyCryptodome isn't available the module raises RuntimeError
to stop operation immediately as required by policy.
"""

import os
import json
import base64
import logging

logger = logging.getLogger("crypto_engine")

try:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa
except Exception as e:
    logger.exception("pycryptodome_missing")
    raise RuntimeError("PyCryptodome not available; failing safe") from e


def aes_encrypt(key: bytes, plaintext: bytes) -> dict:
    try:
        cipher = AES.new(key, AES.MODE_GCM)
        ct, tag = cipher.encrypt_and_digest(plaintext)
        return {
            "nonce": base64.b64encode(cipher.nonce).decode(),
            "ct": base64.b64encode(ct).decode(),
            "tag": base64.b64encode(tag).decode(),
        }
    except Exception:
        logger.exception("aes_encrypt_failed")
        raise


def aes_decrypt(key: bytes, obj: dict) -> bytes:
    try:
        nonce = base64.b64decode(obj["nonce"])
        ct = base64.b64decode(obj["ct"])
        tag = base64.b64decode(obj["tag"])
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ct, tag)
    except Exception:
        logger.exception("aes_decrypt_failed")
        raise


def generate_aes_key() -> bytes:
    return get_random_bytes(32)


def _load_leonel_private_from_env(master_key: bytes) -> ECC.EccKey:
    """Decrypt the `LEONEL_ENC` env var using `master_key` and return Ed25519 key object.

    The encrypted env var is JSON (base64-encoded nonce/ct/tag) stored in `LEONEL_ENC`.
    """
    enc = os.environ.get("LEONEL_ENC")
    if not enc:
        raise RuntimeError("LEONEL_ENC env var missing")
    try:
        data = json.loads(enc)
        raw = aes_decrypt(master_key, data)
        # raw is expected to be a PEM/DER-encoded ECC private key (ed25519)
        key = ECC.import_key(raw)
        return key
    except Exception:
        logger.exception("load_leonel_failed")
        raise


def sign_with_leonel(message: bytes) -> bytes:
    """Sign `message` using LEONEL private key decrypted for minimal time in memory.

    Expects `LEONEL_MASTER_KEY` env var (hex) and `LEONEL_ENC` JSON env var.
    After signing the raw key material is attempted to be cleared.
    """
    mk = os.environ.get("LEONEL_MASTER_KEY")
    if not mk:
        raise RuntimeError("LEONEL_MASTER_KEY missing")
    master_key = bytes.fromhex(mk)
    if len(master_key) not in (16, 24, 32):
        raise RuntimeError("LEONEL_MASTER_KEY must be 16/24/32 bytes hex")

    key_obj = _load_leonel_private_from_env(master_key)
    try:
        signer = eddsa.new(key_obj, mode="rfc8032")
        sig = signer.sign(message)
        return sig
    finally:
        # best-effort zeroization
        try:
            del key_obj
        except Exception:
            pass


def verify_signature(public_raw: bytes, message: bytes, signature: bytes) -> bool:
    try:
        pub = ECC.import_key(public_raw)
        verifier = eddsa.new(pub, mode="rfc8032")
        verifier.verify(message, signature)
        return True
    except Exception:
        logger.exception("signature_verify_failed")
        return False


def sha256_hex(b: bytes) -> str:
    import hashlib

    return hashlib.sha256(b).hexdigest()


__all__ = [
    "aes_encrypt",
    "aes_decrypt",
    "generate_aes_key",
    "sign_with_leonel",
    "verify_signature",
    "sha256_hex",
]
