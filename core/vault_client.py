from __future__ import annotations

import threading
import time
import logging
from typing import Optional

LOGGER = logging.getLogger("core.vault_client")

try:
    import hvac
except Exception:
    hvac = None


class VaultClient:
    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        self.url = url
        self.token = token
        self.client = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._backoff = 1
        self._connected = False
        if hvac is None:
            LOGGER.warning("hvac not available; Vault operating in degraded mode")
            return
        try:
            self.client = hvac.Client(url=self.url, token=self.token)
            # try to read self token info
            if self.client.is_authenticated():
                self._connected = True
                self._start_renewal()
        except Exception:
            LOGGER.exception("Failed initializing hvac client; entering degraded mode")
            self.client = None

    def _start_renewal(self):
        if not hvac or not self.client:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._renew_loop, daemon=True)
        self._thread.start()

    def _renew_loop(self):
        # attempt to renew token periodically; if fails, backoff
        while not self._stop.is_set():
            try:
                # hvac token lookup + renew if short TTL
                lookup = self.client.lookup_token()
                ttl = lookup.get("data", {}).get("ttl", 0)
                if ttl and ttl < 30:
                    self.client.renew_self(minutes=1)
                self._backoff = 1
            except Exception:
                LOGGER.exception("Vault token renewal failed, backing of")
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 30)
            time.sleep(5)

    def get_secret(self, key: str) -> Optional[str]:
        if not self.client:
            return None
        try:
            data = self.client.secrets.kv.v2.read_secret_version(key)
            return data.get("data", {}).get("data", {}).get("value")
        except Exception:
            LOGGER.exception("Failed reading secret %s", key)
            return None

    def health(self) -> bool:
        if not self.client:
            return False
        try:
            return self.client.is_authenticated()
        except Exception:
            return False

    def shutdown(self):
        self._stop.set()
        if self._thread:
            self._thread.join(1.0)
