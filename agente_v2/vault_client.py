"""Minimal Vault client wrapper with graceful fallback for development.

This module provides a small abstraction to retrieve secrets from HashiCorp
Vault. In production, use `hvac` or the official Vault agent and avoid
exposing secrets in logs. The implementation below falls back to an
in-memory stub when Vault is unreachable.
"""

from typing import Any

try:
    import hvac
except Exception:  # pragma: no cover - hvac optional in scaffold
    hvac = None


class VaultClient:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = url
        self.token = token
        self._client = None
        if hvac and self.url:
            try:
                self._client = hvac.Client(url=self.url, token=self.token)
            except Exception:
                self._client = None

        # in-memory fallback for dev/testing
        self._fallback = {}

    def set_fallback(self, path: str, data: dict[str, Any]) -> None:
        self._fallback[path] = data

    def get_secret(self, path: str, key: str, default: Any = None) -> Any:
        if self._client:
            try:
                # kv v2 read
                res = self._client.secrets.kv.v2.read_secret_version(path=path)
                return res["data"]["data"].get(key, default)
            except Exception:
                pass

        # fallback
        return self._fallback.get(path, {}).get(key, default)

    def get_secret_binary(self, path: str, key: str) -> bytes | None:
        """Retrieve a binary secret (e.g., PKCS12) from Vault if available."""
        val = self.get_secret(path, key, None)
        if isinstance(val, (bytes, bytearray)):
            return bytes(val)
        if isinstance(val, str):
            try:
                return val.encode("utf-8")
            except Exception:
                return None
        return None

    def get_private_key(self, path: str, key: str) -> str | dict | None:
        """Return a PEM-encoded private key (A1) or a reference dict (A3) if present.

        A3-style returns are implementation-specific (e.g. a PKCS#11 reference) and
        should be handled by the caller or a platform-specific plugin.
        """
        return self.get_secret(path, key, None)

    def get_certificate(self, path: str, key: str) -> str | None:
        return self.get_secret(path, key, None)
