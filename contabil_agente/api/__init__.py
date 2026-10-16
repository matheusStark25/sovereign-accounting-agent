"""
API Package - Endpoints REST
Arquitetura com RBAC, Multi-tenancy e Auditoria
"""

# Import condicional para evitar dependência circular
try:
    from contabil_agente.api.job_status import register_job_api
except ImportError:
    register_job_api = None

try:
    from contabil_agente.api.v1 import rescisao_bp
except ImportError:
    rescisao_bp = None

__all__ = ["rescisao_bp"]
if register_job_api:
    __all__.append("register_job_api")

__version__ = "1.0.0"
