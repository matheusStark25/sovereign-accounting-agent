from __future__ import annotations
from pathlib import Path
from typing import Optional


class Checkpoint:
    """Very small checkpoint utility storing last processed id/index.

    Stores a single line with the last processed identifier. File is created
    in workspace root by default and is hidden (.progress).
    """

    def __init__(self, path: Path | str = ".progress") -> None:
        self.path = Path(path)

    def read(self) -> Optional[str]:
        if not self.path.exists():
            return None
        try:
            return self.path.read_text(encoding="utf-8").strip() or None
        except Exception:
            return None

    def write(self, last_id: str) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(str(last_id), encoding="utf-8")
        tmp.replace(self.path)

    def remove(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass
