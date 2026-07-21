from __future__ import annotations

import os
from typing import Any


class MockProvider:
    """Simple provider that reads secrets from environment variables.

    Keys requested are uppercased and prefixed with `SECRET_` when looking
    in environment. This is a safe fallback and intended for local/dev only.
    """

    def get(self, path: str) -> Any:
        key = path.upper()
        # Also allow direct env key
        for env_key in (f"SECRET_{key}", key):
            if env_key in os.environ:
                return os.environ[env_key]
        return None
