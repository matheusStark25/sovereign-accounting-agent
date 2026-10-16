"""
Enhanced authentication with HMAC signing, API key management, and origin validation.
Complementa middleware/auth.py com recursos adicionais.
"""

import hashlib
import hmac
import logging
import os
from functools import wraps
from typing import Dict, Optional

from flask import jsonify, request

logger = logging.getLogger(__name__)


# API keys hash database (use .env ou database em produção)
API_KEYS_DB: Dict[str, Dict[str, str]] = {}


def load_api_keys_from_env():
    """Carrega API keys de variáveis de ambiente."""
    keys = {}
    for key, value in os.environ.items():
        if key.startswith("API_KEY_"):
            empresa_id = key.replace("API_KEY_", "").lower()
            key_hash = hashlib.sha256(value.encode()).hexdigest()
            keys[key_hash] = {
                "empresa_id": empresa_id,
                "nome": empresa_id.replace("_", " ").title(),
                "ativo": "true",
            }
    return keys


def validate_api_key_hash(api_key: str) -> Optional[Dict[str, str]]:
    """Valida API key usando hash seguro."""
    if not api_key:
        return None

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    all_keys = {**API_KEYS_DB, **load_api_keys_from_env()}

    empresa_data = all_keys.get(key_hash)
    if empresa_data and empresa_data.get("ativo") == "true":
        return empresa_data
    return None


def validate_origin(allowed_origins: list = None) -> bool:
    """Valida origem da requisição para prevenir CSRF."""
    if allowed_origins is None:
        allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

    origin = request.headers.get("Origin") or request.headers.get("Referer", "")

    if "*" in allowed_origins:
        return True

    for allowed in allowed_origins:
        if origin.startswith(allowed.strip()):
            return True

    return False


def sign_request(data: str, secret: str) -> str:
    """Gera assinatura HMAC-SHA256 para payload."""
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def verify_signature(data: str, signature: str, secret: str) -> bool:
    """Verifica assinatura HMAC de requisição."""
    expected = sign_request(data, secret)
    return hmac.compare_digest(expected, signature)


def require_signature(secret_key: Optional[str] = None):
    """
    Decorator para exigir assinatura HMAC em requests críticos.

    Cliente deve enviar:
    - Header X-Signature: HMAC-SHA256 do body
    - Header X-Timestamp: timestamp da requisição
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if secret_key is None:
                secret = os.getenv("API_SECRET_KEY", "change_me_in_production")
            else:
                secret = secret_key

            signature = request.headers.get("X-Signature")
            timestamp = request.headers.get("X-Timestamp")

            if not signature or not timestamp:
                return (
                    jsonify(
                        {
                            "erro": "Assinatura ou timestamp ausente",
                            "status": "unauthorized",
                        }
                    ),
                    401,
                )

            # Valida timestamp (previne replay attacks)
            import time

            try:
                req_time = float(timestamp)
                if abs(time.time() - req_time) > 300:  # 5 minutos
                    return (
                        jsonify(
                            {"erro": "Timestamp expirado", "status": "unauthorized"}
                        ),
                        401,
                    )
            except ValueError:
                return (
                    jsonify({"erro": "Timestamp inválido", "status": "unauthorized"}),
                    401,
                )

            # Verifica assinatura
            body = request.get_data(as_text=True)
            payload = f"{timestamp}{body}"

            if not verify_signature(payload, signature, secret):
                return (
                    jsonify({"erro": "Assinatura inválida", "status": "unauthorized"}),
                    401,
                )

            return f(*args, **kwargs)

        return decorated_function

    return decorator
