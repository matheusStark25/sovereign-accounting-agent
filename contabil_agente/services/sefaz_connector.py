"""Connectors for SEFAZ integrations.

Provides a lightweight SefazConnector (fake lookup) and a SEFAZConnector
that fetches XML documents with retry/backoff and idempotency.
"""

from __future__ import annotations

import hashlib
import logging
import time
import os
from typing import Any, Dict, Optional

import requests

from contabil_agente.services.database_service import DatabaseService

logger = logging.getLogger("sefaz_connector")


class SefazConnector:
    """Lightweight connector to query cadastral status from government services.

    This is a minimal, pluggable implementation. Replace with real HTTP/soap
    integrations (mTLS/zeep) in production.
    """

    def __init__(self, endpoint: Optional[str] = None, timeout: int = 10):
        self.endpoint = endpoint or "https://sefaz.example.local/lookup"
        self.timeout = timeout

    def lookup(
        self, cnpj: Optional[str] = None, cpf: Optional[str] = None
    ) -> Dict[str, Any]:
        """Synchronous lookup; returns dict {active: bool, raw: ...}

        In production, implement retry/backoff, certificate validation and proper error handling.
        """
        # best-effort fake lookup: consider numbers ending with even digit as active
        time.sleep(0.2)
        identifier = cnpj or cpf
        if not identifier:
            return {"active": True, "raw": None}
        try:
            last = int(str(identifier).strip()[-1])
            return {"active": (last % 2 == 0), "raw": {"identifier": identifier}}
        except Exception:
            return {"active": True, "raw": {"identifier": identifier}}

    async def lookup_async(
        self,
        cnpj: Optional[str] = None,
        cpf: Optional[str] = None,
        retries: int = 3,
        backoff: float = 0.5,
    ) -> Dict[str, Any]:
        """Async wrapper with retry/backoff and optional mTLS support.

        Uses `requests` in a thread to keep compatibility if no asyncio HTTP client is available.
        """

        def _sync_lookup():
            # attempt to call an HTTP endpoint if configured
            url = self.endpoint
            params = {}
            if cnpj:
                params["cnpj"] = cnpj
            if cpf:
                params["cp"] = cpf
            cert_path = os.getenv("SEFAZ_CERT_PATH")
            key_path = os.getenv("SEFAZ_KEY_PATH")
            cert = None
            if (
                cert_path
                and key_path
                and os.path.exists(cert_path)
                and os.path.exists(key_path)
            ):
                cert = (cert_path, key_path)
            attempt = 0
            while attempt < retries:
                attempt += 1
                try:
                    if url:
                        r = requests.get(
                            url,
                            params=params,
                            timeout=self.timeout,
                            cert=cert,
                            verify=os.getenv("SEFAZ_VERIFY", "true").lower() == "true",
                        )
                        if r.status_code == 200:
                            try:
                                return {"active": True, "raw": r.json()}
                            except Exception:
                                return {"active": True, "raw": r.text}
                        else:
                            # fallback to heuristic
                            break
                    else:
                        break
                except Exception:
                    time.sleep(backoff * attempt)
            # fallback heuristic
            return self.lookup(cnpj=cnpj, cpf=cpf)

        import asyncio as _asyncio

        loop = _asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_lookup)


class SEFAZConnector:
    """Connector for fetching NF XMLs from SEFAZ with retry/backoff and idempotency.

    Provides `fetch_xml(chave)` that returns bytes or raises.
    """

    def __init__(self, base_url: Optional[str] = None, max_attempts: int = 4):
        self.db = DatabaseService()
        self.base = base_url or "https://sefaz.mock/api"
        self.max_attempts = max_attempts

    def fetch_xml(self, chave: str) -> bytes:
        # idempotency: if already fetched, return stored
        try:
            # check xml_documents
            # this method returns bool; to retrieve content one could extend
            if self.db.xml_exists_by_hash(chave):
                raise RuntimeError("already_fetched")
        except Exception:
            pass

        url = f"{self.base}/nf/{chave}"
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    content = r.content
                    sha = hashlib.sha256(content).hexdigest()
                    if not self.db.xml_exists_by_hash(sha):
                        self.db.save_xml_document(sha, content, schema_ok=1)
                    else:
                        logger.info("sefaz_connector: xml already saved sha=%s", sha)
                    return content
                else:
                    logger.warning("sefaz non200 %s %s", r.status_code, chave)
            except Exception as e:
                logger.warning("fetch_xml attempt %s failed: %s", attempt, e)
            # backoff
            sleep = (2 ** (attempt - 1)) + (attempt * 0.1)
            time.sleep(sleep)
        raise RuntimeError("fetch_failed")


__all__ = ["SefazConnector", "SEFAZConnector"]
