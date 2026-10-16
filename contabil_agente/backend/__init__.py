"""Backend compatibility shim exporting app and infra objects.

This package centralizes the runtime infra moved out of the monolithic
`contabil_agente.agent_contabil` module so other modules can import
`backend.app` for the Flask application and supporting objects.
"""

__all__ = [
    "app",
    "_vault",
    "_audit_logger",
    "_start_cleanup",
    "_graceful_shutdown",
    "_intelligence",
]
