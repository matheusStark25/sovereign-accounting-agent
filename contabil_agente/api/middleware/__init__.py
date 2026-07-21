"""
Middleware Module - Segurança e Controle de Acesso
"""

from .auth import require_role, get_current_user
from .tenant import validate_tenant, get_tenant_context

__all__ = ["require_role", "get_current_user", "validate_tenant", "get_tenant_context"]
