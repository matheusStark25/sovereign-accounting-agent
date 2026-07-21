"""
Minimal shim for middleware.auth used by some route modules.
"""

import os

"""
This shim is only enabled when DEV_SHIM=1 is set in the environment.
When not set, importing this module will raise ImportError so production
imports don't accidentally rely on development shims.
"""

if os.environ.get("DEV_SHIM", "0") not in ("1", "true", "True"):
    raise ImportError(
        "Dev shim for middleware.auth disabled. Set DEV_SHIM=1 to enable."
    )

from functools import wraps


def get_current_user():
    return None


def get_current_empresa():
    """Return a lightweight EmpresaConfig-like object for dev.

    The real implementation lives in `config_empresas`. This shim returns
    a minimal object with attributes used by route modules.
    """

    class Empresa:
        id = "PUBLIC"
        nome = "Public"
        api_key = ""
        ai_model = "gpt-4"
        ai_temperature = 0.2
        max_tokens = 1024
        assistente_nome = "Assistente"
        db_path = "db/public.sqlite"
        logo_path = None

    return Empresa()


def require_api_key(f):
    @wraps(f)
    def _wrapped(*args, **kwargs):
        # In dev, accept any request; real auth enforces API keys
        return f(*args, **kwargs)

    return _wrapped


def require_auth(f):
    return f
