"""Lightweight MPC-inspired circuit breaker scaffold.

Provides an API for requiring a consensus from three parties: agent, hsm,
and audit instance. Implementation uses local signing callbacks (stubs)
and simple majority check. Replace with real MPC or threshold-signatures
for production-critical guarantees.
"""

import logging
from typing import Callable, Dict

logger = logging.getLogger("mpc_circuit_breaker")


class CircuitBreaker:
    def __init__(self, signers: Dict[str, Callable[[bytes], str]]):
        """signers: mapping role->callable that signs bytes and returns signature string"""
        self.signers = signers

    def require_consensus(self, payload: bytes, threshold: int = 2) -> bool:
        """Ask all signers and accept if at least `threshold` return a non-empty signature."""
        sigs = {}
        for role, signer in self.signers.items():
            try:
                s = signer(payload)
                if s:
                    sigs[role] = s
            except Exception:
                logger.exception("signer_failed %s", role)

        ok = len(sigs) >= threshold
        logger.info("consensus_result roles=%s ok=%s", list(sigs.keys()), ok)
        return ok


def default_local_signer(payload: bytes) -> str:
    """Fallback signer: returns hex hash as pseudo-signature."""
    import hashlib

    return hashlib.sha256(b"local-sign:" + payload).hexdigest()


__all__ = ["CircuitBreaker", "default_local_signer"]
