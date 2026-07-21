from __future__ import annotations

import os
from typing import Any, Protocol


class SecretsProvider(Protocol):
    def get(self, path: str) -> Any:  # simple key-style get
        ...


def get_provider() -> SecretsProvider:
    """Factory for secrets provider. Choose via `SECRET_PROVIDER` env var.

    - 'vault' -> uses internal VaultManager if available
    - 'mock'  -> reads from environment variables
    """
    mode = os.getenv("SECRET_PROVIDER", "mock").lower()
    if mode == "vault":
        try:
            from contabil_agente.security.vault_provider import VaultProvider

            return VaultProvider()
        except Exception:
            # fallback to mock if vault provider not available/healthy
            from contabil_agente.security.mock_provider import MockProvider

            return MockProvider()
    else:
        from contabil_agente.security.mock_provider import MockProvider

        return MockProvider()
