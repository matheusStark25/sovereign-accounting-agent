from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Any

from .config import settings


class AuditLogger:
    """Append-only audit logger.

    If `POSTGRES_DSN` is configured and `asyncpg` is available, this class
    will attempt to write to a simple append-only table. Otherwise it will
    append JSON lines to `logs/audit.log`.
    """

    def __init__(self, logs_dir: str | None = None):
        self.dsn = settings.POSTGRES_DSN
        self.logs_dir = logs_dir or "logs"
        os.makedirs(self.logs_dir, exist_ok=True)

    async def record(
        self,
        action: str,
        user_id: str | None,
        audit_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Redact sensitive fields from metadata before persisting
        def _redact(obj: dict[str, Any]) -> dict[str, Any]:
            redacted = {}
            sensitive_keys = {
                "password",
                "pass",
                "token",
                "secret",
                "api_key",
                "apikey",
            }
            for k, v in (obj or {}).items():
                if isinstance(k, str) and k.lower() in sensitive_keys:
                    redacted[k] = "[REDACTED]"
                else:
                    redacted[k] = v
            return redacted

        entry = {
            "ts": datetime.now(timezone.utc).isoformat() + "Z",
            "action": action,
            "user_id": user_id,
            "audit_id": audit_id,
            "metadata": _redact(metadata or {}),
        }
        # Try Postgres if DSN present and asyncpg installed
        if self.dsn:
            try:
                import asyncpg  # type: ignore[reportMissingImports]

                # ensure table exists (best-effort); create simple append-only table
                conn = await asyncpg.connect(dsn=self.dsn)
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id serial PRIMARY KEY,
                        ts timestamptz NOT NULL,
                        user_id text,
                        audit_id text,
                        action text,
                        metadata jsonb
                    )
                """
                )
                # add trigger to prevent DELETE/UPDATE (append-only enforcement)
                await conn.execute(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_prevent_delete_update') THEN
                            CREATE FUNCTION prevent_audit_delete_update() RETURNS trigger AS $$
                            BEGIN
                                RAISE EXCEPTION 'audit_log is append-only';
                                RETURN NULL;
                            END;
                            $$ LANGUAGE plpgsql;
                            CREATE TRIGGER audit_prevent_delete_update
                                BEFORE DELETE OR UPDATE ON audit_log
                                FOR EACH ROW EXECUTE PROCEDURE prevent_audit_delete_update();
                        END IF;
                    END$$;
                """
                )
                await conn.execute(
                    "INSERT INTO audit_log(ts, user_id, audit_id, action, metadata) VALUES($1,$2,$3,$4,$5)",
                    entry["ts"],
                    entry["user_id"],
                    entry["audit_id"],
                    entry["action"],
                    json.dumps(entry["metadata"]),
                )
                await conn.close()
                return
            except Exception:
                # fall through to file append
                pass

        # file fallback
        path = os.path.join(self.logs_dir, "audit.log")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except PermissionError as e:
            # Best-effort: if we can't write audit file, log warning and continue
            import logging

            logging.getLogger("agente_v2.audit").warning(
                "Audit file write failed (%s): %s", path, e
            )
        except Exception as e:
            import logging

            logging.getLogger("agente_v2.audit").exception(
                "Unexpected error while writing audit file (%s): %s", path, e
            )
