"""PDF retention/cleanup service.

Provides a small service to delete expired PDFs (disk or S3) and remove
their manifest entries. Intended to be run periodically (cron, systemd,
or a background thread).
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from pathlib import Path

from . import pdf_store

LOGGER = logging.getLogger("contabil_agente.pdf_retention")


class PdfRetentionService:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def run_pass(self) -> dict:
        """Run a single cleanup pass. Returns a summary dict."""
        summary = {"deleted": [], "errors": []}
        manifest = pdf_store._load_manifest()
        now = datetime.now(timezone.utc)

        for name, entry in list(manifest.items()):
            try:
                expires = entry.get("expires_at")
                if not expires:
                    # If there is no expires_at, use ttl_days if available
                    ttl = int(entry.get("ttl_days", 0) or 0)
                    if ttl <= 0:
                        continue
                    # fallback: skip (manifest normalizer should provide expires_at)
                    continue

                # parse ISO timestamp
                try:
                    exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                except Exception:
                    LOGGER.exception("Invalid expires_at for %s: %s", name, expires)
                    continue

                if exp_dt <= now:
                    storage = entry.get("storage")
                    LOGGER.info("Expiring PDF %s (storage=%s)", name, storage)
                    if self.dry_run:
                        summary["deleted"].append({"name": name, "storage": storage})
                        continue

                    # delete from storage
                    if storage == "s3":
                        try:
                            s3, bucket = pdf_store._s3_client()
                            if s3 and bucket:
                                s3.delete_object(Bucket=bucket, Key=entry.get("key"))
                        except Exception:
                            LOGGER.exception("Failed deleting S3 object for %s", name)
                            summary["errors"].append(name)
                            continue
                    else:
                        # disk
                        try:
                            p = Path(pdf_store.ROOT) / entry.get("path", "")
                            if p.exists():
                                p.unlink()
                        except Exception:
                            LOGGER.exception("Failed deleting disk file for %s", name)
                            summary["errors"].append(name)
                            continue

                    # remove manifest entry
                    try:
                        pdf_store.remove_metadata(name)
                    except Exception:
                        LOGGER.exception("Failed removing manifest entry for %s", name)
                        summary["errors"].append(name)
                        continue

                    summary["deleted"].append({"name": name, "storage": storage})
            except Exception:
                LOGGER.exception("Unexpected error while processing %s", name)
                summary["errors"].append(name)

        return summary


def create_and_run(dry_run: bool = False) -> dict:
    svc = PdfRetentionService(dry_run=dry_run)
    return svc.run_pass()
