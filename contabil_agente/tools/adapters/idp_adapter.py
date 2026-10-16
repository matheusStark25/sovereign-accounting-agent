from __future__ import annotations

from typing import Dict, Any


class IDPAdapter:
    """Identity Provider adapter scaffold for RBAC/OIDC checks."""

    def __init__(self):
        # role mapping for demo
        self._tokens: Dict[str, Dict[str, Any]] = {}

    def register_token(self, token: str, claims: Dict[str, Any]) -> None:
        self._tokens[token] = claims

    def check_rbac(self, token: str, required_role: str) -> bool:
        claims = self._tokens.get(token)
        if not claims:
            return False
        roles = claims.get("roles", [])
        return required_role in roles
