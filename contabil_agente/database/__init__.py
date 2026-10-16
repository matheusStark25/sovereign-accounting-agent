"""Database package for backward-compatible test imports.

This package provides a lightweight shim so tests that import
`contabil_agente.database.pool` succeed. The real project uses
`contabil_agente.core.database` in most places; this stub is intentionally
minimal and safe for unit tests.
"""

from .pool import DatabasePool

__all__ = ["DatabasePool"]
