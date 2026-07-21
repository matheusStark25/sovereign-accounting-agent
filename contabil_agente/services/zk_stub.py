"""Hashchain-based integrity helpers and LEONEL signature integration.

Implements a simple SHA-256 hashchain: each step H_i = SHA256(H_{i-1} || payload_i).
The chain can be signed with the LEONEL key stored encrypted in env.
"""

import hashlib
import json
import logging
from typing import List, Optional

logger = logging.getLogger("zk_stub")

try:
    from contabil_agente.services.crypto_engine import sign_with_leonel
except Exception:
    logger.exception("crypto_engine_missing_for_zk")
    raise RuntimeError("crypto_engine missing; failing safe")


def create_hashchain(payloads: List[bytes], steps: Optional[int] = None) -> List[str]:
    """Create a SHA-256 hashchain for a list of payloads.

    Each hash is hex string of SHA256(prev_hash_bytes + payload).
    If `steps` is provided and longer than payloads, empty payloads are assumed.
    """
    try:
        n = steps or len(payloads)
        prev = b"\x00" * 32
        chain = []
        for i in range(n):
            p = payloads[i] if i < len(payloads) else b""
            h = hashlib.sha256(prev + p).hexdigest()
            chain.append(h)
            prev = bytes.fromhex(h)
        logger.info(json.dumps({"event": "hashchain_created", "length": len(chain)}))
        return chain
    except Exception:
        logger.exception("create_hashchain_failed")
        raise


def verify_hashchain(chain: List[str], payloads: List[bytes]) -> bool:
    try:
        prev = b"\x00" * 32
        for i, h in enumerate(chain):
            p = payloads[i] if i < len(payloads) else b""
            expected = hashlib.sha256(prev + p).hexdigest()
            if expected != h:
                logger.warning(
                    "hashchain_mismatch %s",
                    json.dumps({"index": i, "expected": expected, "actual": h}),
                )
                return False
            prev = bytes.fromhex(h)
        return True
    except Exception:
        logger.exception("verify_hashchain_failed")
        return False


def sign_chain_head(chain: List[str]) -> bytes:
    """Sign the last hash in the chain with the LEONEL key.

    This loads the key only during the signing operation.
    """
    if not chain:
        raise ValueError("empty chain")
    head = chain[-1].encode("utf-8")
    try:
        sig = sign_with_leonel(head)
        logger.info(json.dumps({"event": "chain_signed", "head": chain[-1]}))
        return sig
    except Exception:
        logger.exception("sign_chain_failed")
        raise


__all__ = ["create_hashchain", "verify_hashchain", "sign_chain_head"]
