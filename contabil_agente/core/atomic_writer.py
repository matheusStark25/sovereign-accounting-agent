from __future__ import annotations
from pathlib import Path
import hmac
import hashlib
from typing import Optional


def compute_hash(data: bytes, key: Optional[str] = None) -> str:
    if key:
        dig = hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()
    else:
        dig = hashlib.sha256(data).hexdigest()
    return dig


def atomic_write_bytes(target: Path, data: bytes) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    tmp.replace(target)
