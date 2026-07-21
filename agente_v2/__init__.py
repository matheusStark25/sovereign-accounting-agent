"""Agente Contábil V2 package scaffold."""

__all__ = ["main", "auth", "config", "vault_client", "logging_setup"]

# Provide module-level references to satisfy editors/type-checkers when package
# exports are declared but modules may be imported dynamically in some setups.
try:
	from . import main  # type: ignore[reportMissingImports]
except Exception:
	main = None

try:
	from . import auth  # type: ignore[reportMissingImports]
except Exception:
	auth = None

try:
	from . import config  # type: ignore[reportMissingImports]
except Exception:
	config = None

try:
	from . import vault_client  # type: ignore[reportMissingImports]
except Exception:
	vault_client = None

try:
	from . import logging_setup  # type: ignore[reportMissingImports]
except Exception:
	logging_setup = None
