from datetime import datetime, timedelta
from typing import Optional

try:
    from jose import jwt, JWTError  # type: ignore
except Exception:
    jwt = None
    JWTError = Exception

try:
    from passlib.context import CryptContext
except Exception:
    CryptContext = None

from .config import settings

if CryptContext is not None:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
else:
    import hashlib
    import os
    import hmac

    class _SimpleContext:
        def hash(self, password: str) -> str:
            salt = os.urandom(8)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
            return salt.hex() + ":" + dk.hex()

        def verify(self, plain: str, hashed: str) -> bool:
            try:
                s, dk = hashed.split(":", 1)
                salt = bytes.fromhex(s)
                expected = bytes.fromhex(dk)
                check = hashlib.pbkdf2_hmac(
                    "sha256", plain.encode("utf-8"), salt, 100000
                )
                return hmac.compare_digest(check, expected)
            except Exception:
                return False

    pwd_context = _SimpleContext()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    # If jose is available use it; otherwise use a simple HMAC-signed token.
    now = datetime.utcnow()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire.timestamp(), "iat": now.timestamp()}
    if jwt:
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    # simple HMAC JSON-based token (not RFC-compliant, for tests/dev only)
    import json
    import base64
    import hmac
    import hashlib

    b = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    sig = hmac.new(settings.SECRET_KEY.encode(), b, hashlib.sha256).digest()
    s = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return b.decode() + "." + s.decode()


def decode_access_token(token: str) -> dict:
    if jwt:
        try:
            return jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
        except JWTError:
            raise
    # decode our simple HMAC token
    import json
    import base64
    import hmac
    import hashlib

    try:
        b64, sig = token.split(".")
        b = b64.encode()
        expected_sig = base64.urlsafe_b64encode(
            hmac.new(settings.SECRET_KEY.encode(), b, hashlib.sha256).digest()
        ).rstrip(b"=")
        if not hmac.compare_digest(expected_sig, sig.encode()):
            raise Exception("invalid signature")
        payload = json.loads(base64.urlsafe_b64decode(b + b"==").decode())
        # validate expiry
        if payload.get("exp") and payload["exp"] < datetime.utcnow().timestamp():
            raise Exception("token expired")
        return payload
    except Exception:
        raise
