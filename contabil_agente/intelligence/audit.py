"""ForensicAudit implementation for tests and lightweight persistence.

This writes a newline-delimited JSON file to `contabil_agente/data/forensic_audit.jsonl`.
Each record contains the request_id, session_id, timestamp, input and output.
Designed to be small and deterministic for local E2E runs.
"""

from typing import Any
import json
import os
from datetime import datetime
from pathlib import Path


class ForensicAudit:
    def __init__(self):
        self.name = "forensic_audit"
        root = Path(__file__).resolve().parents[1]
        self.data_dir = root / "data"
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.log_path = self.data_dir / "forensic_audit.jsonl"

    def record(
        self, request_id: str, session_id: str, input_sanitized: Any, output: Any
    ) -> None:
        try:
            # Anonymize sensitive PII from input_sanitized before writing
            safe_input = _anonymize_input(input_sanitized)
            safe_output = _anonymize_output(output)

            entry = {
                "request_id": request_id,
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "input": safe_input,
                "output": safe_output,
            }
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # Rotate log if it grows too large (simple renaming strategy)
            try:
                max_bytes = int(os.getenv("AUDIT_MAX_BYTES", str(5 * 1024 * 1024)))
                if self.log_path.exists() and self.log_path.stat().st_size > max_bytes:
                    rotated = self.data_dir / ("forensic_audit.jsonl.1")
                    try:
                        if rotated.exists():
                            rotated.unlink()
                    except Exception:
                        pass
                    try:
                        self.log_path.replace(rotated)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            # Swallow errors to avoid breaking the main flow during tests
            return


def _anonymize_input(obj: Any) -> Any:
    """Strip or mask PII from input structures: CPF numbers and obvious full names."""
    try:
        import re

        def mask_str(s: str) -> str:
            # mask CPFs (formatted or plain 11 digits)
            s = re.sub(
                r"\b(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2}|\d{11})\b",
                "[REDACTED_CPF]",
                s,
            )
            # mask sequences of two capitalized words (likely names) by initials
            s = re.sub(
                r"\b([A-ZÀ-Ú][a-zà-ú]{1,})\s+([A-ZÀ-Ú][a-zà-ú]{1,})\b",
                lambda m: f"{m.group(1)[0]}. {m.group(2)[0]}.",
                s,
            )
            return s

        if obj is None:
            return None
        if isinstance(obj, str):
            return mask_str(obj)
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                out[k] = _anonymize_input(v)
            return out
        if isinstance(obj, list):
            return [_anonymize_input(i) for i in obj]
        return obj
    except Exception:
        return obj


def _anonymize_output(obj: Any) -> Any:
    # For now, apply same masking rules as input
    return _anonymize_input(obj)
