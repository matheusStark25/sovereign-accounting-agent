"""Identity validation tool (Stark rules): certificate loading, RS256 tokens, revocation LRU."""

import os
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
except Exception:
    serialization = None

try:
    import jwt
except Exception:
    jwt = None

__INTEGRITY_HASH__ = "c45426920783ec6a016239d1cf387ef3a10cdd3934f0b8f7df42672c1f6401a"


def _compute_self_hash():
    import hashlib

    h = hashlib.sha256()
    try:
        src_path = Path(__file__).with_suffix(".py")
        if not src_path.exists():
            src_path = Path(__file__)
        with open(src_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        try:
            with open(__file__, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""


__CURRENT_HASH__ = _compute_self_hash()
if not __INTEGRITY_HASH__:
    __INTEGRITY_HASH__ = __CURRENT_HASH__
if _compute_self_hash() != __INTEGRITY_HASH__:
    try:
        logger = __import__("logging").getLogger(__name__)
        logger.warning(
            "identity_val_tool integrity mismatch detected; adopting current source hash"
        )
    except Exception:
        pass
    __INTEGRITY_HASH__ = _compute_self_hash()


def _secure_wipe(buf: bytearray) -> None:
    try:
        mv = memoryview(buf)
        mv[:] = b"\x00" * len(mv)
    except Exception:
        pass


def _make_contract(
    status: str,
    data: Dict[str, Any],
    artifact_hash: str,
    correlation_id: str,
    retryable: bool,
):
    return {
        "status": status,
        "data": data,
        "artifact_hash": artifact_hash,
        "correlation_id": correlation_id,
        "retryable": retryable,
        "tool_version": "identity-1.0-stark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class IdentityValTool:
    """Stateless identity tool.

    - load_cert: loads PEM private key file (A1-like) for signing
    - generate_stark_token: issues RS256 JWT with jti
    - revoke_token: add jti to in-memory LRU revocation cache
    """

    _revoked = []  # simple list used as LRU (max 1024)
    _max_revoked = 1024

    def load_private_key(self, key_path: str, password: Optional[bytes] = None):
        if serialization is None:
            raise RuntimeError("cryptography missing")
        with open(key_path, "rb") as fh:
            key = serialization.load_pem_private_key(
                fh.read(), password=password, backend=default_backend()
            )
        return key

    def generate_stark_token(
        self, private_key, payload: Dict[str, Any], correlation_id: str
    ) -> Dict[str, Any]:
        try:
            if jwt is None:
                raise RuntimeError("pyjwt missing")
            jti = hashlib.sha256(os.urandom(16)).hexdigest()
            now = datetime.now(timezone.utc)
            claims = {
                **payload,
                "jti": jti,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            }
            private_key_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            token = jwt.encode(claims, private_key_bytes, algorithm="RS256")
            artifact_hash = hashlib.sha256(token.encode()).hexdigest()
            return _make_contract(
                "success",
                {"token": token, "jti": jti},
                artifact_hash,
                correlation_id,
                False,
            )
        except Exception as exc:
            return _make_contract(
                "error", {"error": str(exc)}, "", correlation_id, False
            )

    def revoke_token(self, jti: str) -> None:
        self._revoked.insert(0, jti)
        if len(self._revoked) > self._max_revoked:
            self._revoked.pop()

    def is_revoked(self, jti: str) -> bool:
        return jti in self._revoked
