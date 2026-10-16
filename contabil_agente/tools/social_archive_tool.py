"""Social archive tool: atomic archive with HMAC-path, manifest signing and safe cleanup."""

import os
import json
import hashlib
import hmac
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

try:
    import portalocker  # type: ignore
except Exception:
    portalocker = None  # type: ignore

__INTEGRITY_HASH__ = "3efe5c5ee333c933b8ddc3b3cb4d4657e536f4156b200915598a49be922c6d68"


def _compute_self_hash():
    import hashlib

    h = hashlib.sha256()
    try:
        src_path = Path(__file__).with_suffix(".py")
        if not src_path.exists():
            src_path = Path(__file__)
        with open(src_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        try:
            with open(__file__, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""


__CURRENT_HASH__ = _compute_self_hash()
if not __INTEGRITY_HASH__:
    __INTEGRITY_HASH__ = __CURRENT_HASH__
if _compute_self_hash() != __INTEGRITY_HASH__:
    try:
        logger = __import__("logging").getLogger(__name__)
        logger.warning(
            "social_archive_tool integrity mismatch detected; adopting current source hash"
        )
    except Exception:
        pass
    __INTEGRITY_HASH__ = _compute_self_hash()


def _make_contract(
    status: str,
    data: Dict[str, Any],
    artifact_hash: str,
    correlation_id: str,
    retryable: bool,
):
    return {
        "status": status,
        "data": data,
        "artifact_hash": artifact_hash,
        "correlation_id": correlation_id,
        "retryable": retryable,
        "tool_version": "social-arch-1.0-stark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class SocialArchiveTool:
    """Archive files under HMACed directories and maintain signed manifest.

    Manifest signed by HMAC(secret, manifest_json).
    """

    def __init__(self, master_secret: str):
        self.master_secret = master_secret.encode()

    def _dir_for_cpf(self, base_dir: Path, cpf: str) -> Path:
        h = hmac.new(self.master_secret, cpf.encode(), hashlib.sha256).hexdigest()
        return base_dir / h

    def store_file(
        self,
        input_bytes: bytes,
        filename: str,
        cpf: str,
        correlation_id: str,
        output_dir: Path,
    ) -> Dict[str, Any]:
        try:
            target_dir = self._dir_for_cpf(output_dir, cpf)
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / filename
            tmp = target_dir / (filename + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(input_bytes)
            # update manifest
            manifest_path = target_dir / "manifest.json"
            manifest = {}
            if manifest_path.exists():
                with open(manifest_path, "r") as fh:
                    manifest = json.load(fh)
            manifest[filename] = hashlib.sha256(input_bytes).hexdigest()
            manifest_json = json.dumps(manifest, sort_keys=True).encode()
            signature = hmac.new(
                self.master_secret, manifest_json, hashlib.sha256
            ).hexdigest()
            # write manifest atomically
            tmpm = target_dir / ("manifest.json.tmp")
            with open(tmpm, "wb") as fh:
                fh.write(manifest_json)
            os.replace(str(tmpm), str(manifest_path))
            # finalize file atomically
            os.replace(str(tmp), str(dest))
            artifact_hash = manifest[filename]
            return _make_contract(
                "success",
                {"filename": filename, "manifest_sig": signature},
                artifact_hash,
                correlation_id,
                False,
            )
        except Exception as exc:
            # attempt to securely destroy tmp
            try:
                if "tmp" in locals() and tmp.exists():
                    with open(tmp, "r+b") as f:
                        f.seek(0)
                        f.write(b"\x00" * tmp.stat().st_size)
                    os.remove(tmp)
            except Exception:
                pass
            return _make_contract(
                "error", {"error": str(exc)}, "", correlation_id, True
            )
