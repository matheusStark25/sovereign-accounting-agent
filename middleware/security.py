"""
Minimal shim of middleware.security to allow route modules to import in dev.
Provides permissive no-op implementations suitable for local testing only.
"""

from functools import wraps
from flask import jsonify


def get_current_operator_id():
    return None


def get_current_tenant_id():
    return None


def is_operator_admin():
    return False


def mask_pii_in_response(data, pii_fields):
    # No-op masking for dev
    return data


def require_security(permission=None, audit_action=None, resource_type=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator
