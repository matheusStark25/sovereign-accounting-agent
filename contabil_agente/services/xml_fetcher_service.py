"""XML fetcher for Prefeitura/SEFAZ APIs with degraded mode.
Claims tasks from DatabaseService and tries to fetch XML by chave.
"""

import time
import requests
import json
from typing import Optional

from .database_service import DatabaseService
from .configuration import get_config
from .event_bus import get_event_bus
import hashlib

try:
    from lxml import etree
except Exception:
    etree = None

DEFAULTS = {"mode": "NORMAL", "sefaz_base": "https://sefaz.mock/api"}


class XMLFetcherService:
    def __init__(self, config_path: Optional[str] = None):
        cfg = get_config(yaml_path=config_path, defaults=DEFAULTS)
        self.mode = cfg.get("mode", "NORMAL")
        self.sefaz_base = cfg.get("sefaz_base")
        self.db = DatabaseService()
        self.bus = get_event_bus()

    def fetch_for_chave(self, chave: str) -> Optional[str]:
        url = f"{self.sefaz_base}/nf/{chave}"
        # exponential backoff retries
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    return r.content.decode("utf-8")
                else:
                    self.db._audit(
                        f"XML_FETCH_NON200 chave={chave} status={r.status_code}"
                    )
                    if self.mode == "DEGRADADO":
                        return None
                # non-200 triggers retry
            except Exception as e:
                self.db._audit(f"XML_FETCH_ERROR chave={chave} error={e}")
                if self.mode == "DEGRADADO":
                    return None
            # backoff
            sleep_for = (2 ** (attempt - 1)) + (attempt * 0.1)
            time.sleep(sleep_for)
        return None

    def run_poll(self):
        # Claim tasks from DB for XML fetch work (tasks enqueued by triagem)
        while True:
            t = self.db.claim_task(priority=None)
            if not t:
                time.sleep(1)
                continue
            task_id = t["id"]
            payload = {}
            try:
                payload = json.loads(t.get("payload") or "{}")
            except Exception:
                pass
            chave = payload.get("chave") or payload.get("file")
            try:
                xml = self.fetch_for_chave(chave)
                # store or attach
                if xml:
                    content_bytes = xml.encode("utf-8")
                    sha = hashlib.sha256(content_bytes).hexdigest()
                    # idempotency check
                    if self.db.xml_exists_by_hash(sha):
                        self.db._audit(f"XML already processed sha={sha}")
                    else:
                        # validate schema if available
                        schema_ok = False
                        if etree:
                            try:
                                # quick parse (parse for well-formedness; result not needed)
                                etree.fromstring(content_bytes)
                                schema_ok = True
                            except Exception as e:
                                self.db._audit(f"XML schema/parse error: {e}")
                                schema_ok = False
                        # save to DB
                        try:
                            self.db.save_xml_document(
                                sha, content_bytes, schema_ok=schema_ok
                            )
                            # record processing checkpoint
                            self.db.record_processamento(
                                chave,
                                "xml_fetched",
                                json.dumps({"sha": sha, "schema_ok": schema_ok}),
                            )
                            # publish event
                            try:
                                self.bus.publish(
                                    "document.xml_ingested",
                                    {"chave": chave, "sha": sha},
                                    correlation_id=chave,
                                )
                            except Exception:
                                pass
                        except Exception:
                            self.db._audit("failed to save xml document")

                # complete task
                self.db.complete_task(task_id)
            except Exception as e:
                self.db.fail_task(task_id, str(e))


__all__ = ["XMLFetcherService"]
