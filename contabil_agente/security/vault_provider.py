from __future__ import annotations

from typing import Any
import logging

logger = logging.getLogger(__name__)

try:
    from contabil_agente.security.vault_manager import VaultManager
except Exception:
    VaultManager = None  # type: ignore


class VaultProvider:
    """Provider that fetches secrets from the in-repo VaultManager (or an hvac client behind it).

    Falls back to raising a clear exception if VaultManager is not usable.
    """

    def __init__(self):
        if VaultManager is None:
            raise RuntimeError("VaultManager not available in this runtime")
        self._vm = VaultManager()

    def get(self, path: str) -> Any:
        # path is a simple key; VaultManager exposes a cached interface
        try:
            # VaultManager stores keys in lowercase mapping used by repo
            val = getattr(self._vm, "_secrets_cache", {}).get(path)
            if val is not None:
                return val
            # last-resort: try attribute access
            return getattr(self._vm, path)
        except Exception as e:
            logger.exception("VaultProvider get failed for %s: %s", path, e)
            raise
