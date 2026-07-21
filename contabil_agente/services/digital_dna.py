"""Digital DNA: capture and persist process/window identity for legacy systems.

Uses `psutil` and `pygetwindow` to capture PID, HWND and Title. Stores checkpoints
in an SQLite DB under data/digital_dna.db. Includes validation of PIDs on restart.
"""

import os
import json
import sqlite3
import logging
from typing import Optional, Dict

logger = logging.getLogger("digital_dna")

try:
    import psutil
    import pygetwindow as gw
except Exception as e:
    logger.exception("digital_dna_deps_missing")
    raise RuntimeError("psutil or pygetwindow missing; failing safe") from e

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "digital_dna.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL;")
    return c


def init_db():
    try:
        c = _conn()
        c.execute("""CREATE TABLE IF NOT EXISTS checkpoints(
            tag TEXT PRIMARY KEY,
            ts INTEGER,
            pid INTEGER,
            hwnd INTEGER,
            title TEXT,
            state BLOB
        );""")
        c.commit()
        c.close()
    except Exception:
        logger.exception("digital_dna_init_failed")


def capture_legacy_process(name_hint: str) -> Optional[Dict]:
    """Try to find a process whose name or window title matches `name_hint`.

    Returns dict with pid, hwnd, title or None.
    """
    try:
        # find processes by name
        for p in psutil.process_iter(["pid", "name"]):
            if name_hint.lower() in (p.info.get("name") or "").lower():
                pid = p.info["pid"]
                # try to find window for this pid
                for w in gw.getAllWindows():
                    if getattr(w, "_hWnd", None) and hasattr(w, "title"):
                        if w._hWnd and w.title and pid == getattr(w, "_hWnd", None):
                            return {"pid": pid, "hwnd": w._hWnd, "title": w.title}
                # fallback: return pid with empty hwnd/title
                return {"pid": pid, "hwnd": None, "title": None}
    except Exception:
        logger.exception("capture_legacy_failed")
    return None


def save_checkpoint(
    tag: str, pid: int, hwnd: Optional[int], title: Optional[str], state_blob: bytes
) -> None:
    try:
        c = _conn()
        c.execute(
            "REPLACE INTO checkpoints(tag, ts, pid, hwnd, title, state) VALUES(?, strftime('%s','now'), ?, ?, ?, ?)",
            (tag, pid, hwnd, title, state_blob),
        )
        c.commit()
        c.close()
        logger.info(
            json.dumps(
                {
                    "event": "dna_checkpoint_saved",
                    "tag": tag,
                    "pid": pid,
                    "hwnd": hwnd,
                    "title": title,
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        logger.exception("save_checkpoint_failed")


def load_checkpoint(tag: str) -> Optional[Dict]:
    try:
        c = _conn()
        cur = c.execute(
            "SELECT tag, ts, pid, hwnd, title, state FROM checkpoints WHERE tag=?",
            (tag,),
        )
        row = cur.fetchone()
        c.close()
        if not row:
            return None
        return {
            "tag": row[0],
            "ts": row[1],
            "pid": row[2],
            "hwnd": row[3],
            "title": row[4],
            "state": row[5],
        }
    except Exception:
        logger.exception("load_checkpoint_failed")
        return None


def validate_pid(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception:
        logger.exception("validate_pid_failed")
        return False


init_db()

__all__ = [
    "capture_legacy_process",
    "save_checkpoint",
    "load_checkpoint",
    "validate_pid",
]
