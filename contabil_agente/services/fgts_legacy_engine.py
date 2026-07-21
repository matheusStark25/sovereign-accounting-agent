"""FGTS legacy engine: scan old FGTS PDFs for PIS, names and balances.

Features:
- Uses `pdfplumber` to extract text from PDFs (guarded import).
- Scans a directory of PDFs and looks for PIS patterns (###.#####.##-#).
- For each match emits a JSON line to a local log with keys:
  `funcionario_nome`, `pis_encontrado`, `saldo_base`, `fonte_arquivo`.
- Persists progress to a state file and calls `continuity_service.atomic_checkpoint`
  after each file so a resumed run continues after the last processed file.

Notes:
- Install dependency: `pip install pdfplumber` (and its deps).
- The name/saldo heuristics are conservative heuristics and may need tuning
  for different PDF layouts.
"""

from __future__ import annotations
import os
import re
import json
import logging
from typing import Optional, Dict, Any, List
import shutil
import sqlite3
import hashlib
from datetime import datetime, timezone

try:
    import pywinauto  # type: ignore[import]
except Exception:  # pragma: no cover - runtime optional
    pywinauto = None

try:
    import pyautogui  # type: ignore
except Exception:  # pragma: no cover - runtime optional
    pyautogui = None

DEFAULT_DB = "./fgts_legacy_checkpoint.db"

logger = logging.getLogger("fgts_legacy_engine")

# guarded import for pdfplumber
try:
    import pdfplumber  # type: ignore
except Exception:
    pdfplumber = None

try:
    from contabil_agente.services.continuity_service import atomic_checkpoint
except Exception:
    atomic_checkpoint = None

try:
    from contabil_agente.services.digital_dna import (
        save_checkpoint as dna_save_checkpoint,
    )
except Exception:
    dna_save_checkpoint = None


PIS_RE = re.compile(r"\b\d{3}\.\d{5}\.\d{2}-\d\b")
CURR_RE = re.compile(r"R\$\s?[\d\.,]+|\b\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{2})\b")
NAME_RE = re.compile(
    r"(?:Nome|Funcion[aá]rio|Titular)[:\s]*([A-ZÀ-Ý][A-Za-zÀ-ÿ'`\-\.\s]{2,80})"
)


class FGTSLegacyEngine:
    def __init__(
        self,
        source_dir: str,
        base_path: Optional[str] = None,
        db: Optional[Any] = None,
        state_file: Optional[str] = None,
        log_file: Optional[str] = None,
    ):
        self.source_dir = os.path.abspath(source_dir)
        self.base_path = base_path or os.getenv("STARK_BASE_PATH", "./stark_data")
        os.makedirs(self.base_path, exist_ok=True)
        self.db = db
        self.state_file = state_file or os.path.join(
            self.base_path, "fgts_scan_state.json"
        )
        self.log_file = log_file or os.path.join(
            self.base_path, "fgts_legacy_logs.jsonl"
        )
        # load state
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                logger.exception("failed_load_state")
        return {"last_processed": None}

    def _save_state(self, last_processed: str) -> None:
        self._state["last_processed"] = last_processed
        try:
            with open(self.state_file, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, ensure_ascii=False)
        except Exception:
            logger.exception("failed_save_state")

    def _append_log(self, entry: Dict[str, Any]) -> None:
        try:
            with open(self.log_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("failed_append_log")

    def _extract_candidates(self, text: str) -> List[Dict[str, Optional[str]]]:
        out: List[Dict[str, Optional[str]]] = []
        if not text:
            return out
        # find all PIS occurrences
        for m in PIS_RE.finditer(text):
            pis = m.group(0)
            # heuristic: search nearby for name or currency
            window_start = max(0, m.start() - 200)
            window_end = min(len(text), m.end() + 200)
            window = text[window_start:window_end]
            name = None
            saldo = None
            nm = NAME_RE.search(window)
            if nm:
                name = nm.group(1).strip()
            # currency search
            cm = CURR_RE.search(window)
            if cm:
                saldo = cm.group(0)
            out.append({"pis": pis, "name": name, "saldo": saldo})
        return out

    def process_pdf(self, path: str) -> List[Dict[str, Optional[str]]]:
        results: List[Dict[str, Optional[str]]] = []
        if not pdfplumber:
            raise RuntimeError(
                "pdfplumber is required. Install with: pip install pdfplumber"
            )
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    try:
                        text = page.extract_text() or ""
                        candidates = self._extract_candidates(text)
                        for c in candidates:
                            results.append(c)
                    except Exception:
                        logger.exception("page_extract_failed %s", path)
        except Exception:
            logger.exception("pdf_open_failed %s", path)
        return results

    def _compute_hash(self, path: str) -> str:
        """Compute SHA256 hash for a file (used for checkpointing)."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def scan(self) -> None:
        # list pdfs sorted
        files = [f for f in os.listdir(self.source_dir) if f.lower().endswith(".pd")]
        files.sort()
        last = self._state.get("last_processed")
        start_idx = 0
        if last and last in files:
            start_idx = files.index(last) + 1

        for fname in files[start_idx:]:
            path = os.path.join(self.source_dir, fname)
            try:
                logger.info("processing_fgts %s", path)
                items = self.process_pdf(path)
                if not items:
                    logger.info("no_pis_found %s", path)
                for it in items:
                    entry = {
                        "funcionario_nome": it.get("name"),
                        "pis_encontrado": it.get("pis"),
                        "saldo_base": it.get("saldo"),
                        "fonte_arquivo": fname,
                    }
                    self._append_log(entry)
                # persist state and checkpoint
                try:
                    self._save_state(fname)
                    # Prefer digital_dna checkpoint if available (stores pid/window info etc.)
                    try:
                        # compute file hash for checkpointing
                        file_hash = self._compute_hash(path)
                        state_blob = file_hash.encode("utf-8")
                        if dna_save_checkpoint is not None:
                            try:
                                dna_save_checkpoint(
                                    tag=fname,
                                    pid=0,
                                    hwnd=None,
                                    title=fname,
                                    state_blob=state_blob,
                                )
                            except Exception:
                                logger.exception("dna_save_checkpoint_failed %s", fname)
                        elif atomic_checkpoint and self.db:
                            try:
                                atomic_checkpoint(self.db, tag=fname)
                            except Exception:
                                logger.exception("atomic_checkpoint_failed %s", fname)
                    except Exception:
                        logger.exception("checkpoint_integration_failed %s", fname)
                except Exception:
                    logger.exception("state_persist_failed %s", fname)
            except Exception:
                logger.exception("processing_file_failed %s", path)


def run_scan_from_dir(dir_path: str, db: Optional[Any] = None):
    eng = FGTSLegacyEngine(source_dir=dir_path, db=db)
    eng.scan()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("dir", help="Directory with FGTS PDF files")
    p.add_argument("--base", help="Base path for state/logs (optional)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_scan_from_dir(args.dir)


class FGTSEngine:
    """Engine to scan legacy PDFs for PIS/CPF and FGTS balances

    Features:
    - Recursive scan of `historico_fgts` (configurable)
    - Uses `pdfplumber` to extract text
    - Regex detection for PIS, CPF and monetary balances
    - Checkpointing via injectable `continuity_service` or SQLite fallback
    - Quarantine for corrupted/password-protected PDFs
    - JSON-line audit logs written to `fgts_legacy.log.jsonl`
    - Lightweight automation hooks using `pywinauto`/`pyautogui` (safe fallbacks)
    """

    PIS_REGEX = re.compile(r"\d{3}\.\d{5}\.\d{2}-\d{1}")
    CPF_REGEX = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
    # Capture money after keywords Saldo/Base/Total (allow R$ or not)
    SALDO_REGEX = re.compile(
        r"(?:Saldo|Base|Total)\W{0,10}?R?\$?\s*([0-9\.\,]+)", re.IGNORECASE
    )
    NOME_REGEX = re.compile(r"Nome[:\s]+([A-ZÀ-Ÿ][A-Za-zÀ-ÿ\s\-]{2,80})", re.IGNORECASE)

    def __init__(
        self,
        root_dir: str = "./historico_fgts",
        db_path: str = DEFAULT_DB,
        quarantine_dir: Optional[str] = None,
        continuity_service: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.root_dir = os.path.abspath(root_dir)
        self.db_path = os.path.abspath(db_path)
        self.quarantine_dir = (
            os.path.join(self.root_dir, "quarantine")
            if quarantine_dir is None
            else quarantine_dir
        )
        self.continuity_service = continuity_service
        self.logfile = os.path.abspath("fgts_legacy.log.jsonl")

        if logger is None:
            self.logger = logging.getLogger("FGTSEngine")
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
        else:
            self.logger = logger

        self._ensure_dirs()
        self._init_db()

    def _ensure_dirs(self) -> None:
        os.makedirs(self.root_dir, exist_ok=True)
        os.makedirs(self.quarantine_dir, exist_ok=True)

    def _init_db(self) -> None:
        # If a continuity_service is provided and looks like it manages checkpoints, prefer it
        if self.continuity_service is not None:
            try:
                # simple probe: continuity_service should have is_processed/mark_processed methods
                if hasattr(self.continuity_service, "is_processed") and hasattr(
                    self.continuity_service, "mark_processed"
                ):
                    self.logger.info(
                        "Using provided continuity_service for checkpoints"
                    )
                    return
            except Exception:
                self.logger.exception(
                    "continuity_service probe failed; falling back to sqlite"
                )

        # SQLite fallback
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS processed_files (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT,
                processed_at TEXT
            )
            """)
        self._conn.commit()

    def _compute_hash(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _is_processed(self, file_path: str, file_hash: str) -> bool:
        if self.continuity_service is not None and hasattr(
            self.continuity_service, "is_processed"
        ):
            try:
                return bool(
                    self.continuity_service.is_processed(
                        file_hash=file_hash, file_path=file_path
                    )
                )
            except Exception:
                self.logger.exception(
                    "continuity_service.is_processed failed; falling back to sqlite check"
                )

        cur = self._conn.cursor()
        cur.execute(
            "SELECT file_hash FROM processed_files WHERE file_path = ?", (file_path,)
        )
        row = cur.fetchone()
        return bool(row and row[0] == file_hash)

    def _mark_processed(self, file_path: str, file_hash: str) -> None:
        if self.continuity_service is not None and hasattr(
            self.continuity_service, "mark_processed"
        ):
            try:
                self.continuity_service.mark_processed(
                    file_hash=file_hash, file_path=file_path
                )
                return
            except Exception:
                self.logger.exception(
                    "continuity_service.mark_processed failed; falling back to sqlite mark"
                )

        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO processed_files (file_path, file_hash, processed_at) VALUES (?, ?, ?)",
            (file_path, file_hash, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def _append_log(self, payload: Dict[str, Any]) -> None:
        # Write one JSON object per line for easy forensics
        with open(self.logfile, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _quarantine(self, src_path: str, reason: str) -> None:
        try:
            base = os.path.basename(src_path)
            dest = os.path.join(
                self.quarantine_dir,
                f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{base}",
            )
            shutil.move(src_path, dest)
            self.logger.warning(
                "Moved corrupted/protected file to quarantine: %s", dest
            )
            self._append_log(
                {
                    "event": "quarantine",
                    "source": src_path,
                    "dest": dest,
                    "reason": reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception:
            self.logger.exception("Failed to move file to quarantine: %s", src_path)

    def _extract_text_from_pdf(self, path: str) -> str:
        if pdfplumber is None:
            raise RuntimeError("pdfplumber is required but not installed")
        text_parts = []
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    try:
                        text = page.extract_text() or ""
                        text_parts.append(text)
                    except Exception:
                        # page-level extraction failure shouldn't abort whole file
                        self.logger.exception("Failed to extract page in %s", path)
            return "\n".join(text_parts)
        except Exception:
            # Could be encrypted or corrupted
            raise

    def _parse_document(self, text: str) -> Dict[str, Optional[Any]]:
        pis = self.PIS_REGEX.findall(text)
        cpf = self.CPF_REGEX.findall(text)
        saldos = self.SALDO_REGEX.findall(text)
        nome = None
        m = self.NOME_REGEX.search(text)
        if m:
            nome = m.group(1).strip()

        def parse_money(s: str) -> Optional[float]:
            try:
                # Normalize: '1.234,56' or '1234.56' -> float
                if s.count(",") > 0 and s.count(".") > 0:
                    s2 = s.replace(".", "").replace(",", ".")
                else:
                    s2 = s.replace(",", ".")
                return float(s2)
            except Exception:
                return None

        parsed_saldos = [parse_money(s) for s in saldos if parse_money(s) is not None]

        return {
            "nome": nome,
            "pis": pis[0] if pis else None,
            "cp": cpf[0] if cpf else None,
            "saldos": parsed_saldos,
        }

    def _reconcile(
        self, local_balance: Optional[float], gov_balance: Optional[float]
    ) -> Dict[str, Any]:
        local = float(local_balance) if local_balance is not None else 0.0
        gov = float(gov_balance) if gov_balance is not None else 0.0
        diff = round(local - gov, 2)
        status = "OK"
        if abs(diff) > 0.01:
            status = "CRITICAL_DIVERGENCE"
        return {
            "local_balance": local,
            "gov_balance": gov,
            "dif": diff,
            "status": status,
        }

    def _query_gov_portal(self, pis_or_cpf: str) -> Optional[float]:
        # Try pywinauto first; if not available or fails, attempt pyautogui fallback.
        # For safety, do not attempt to start browsers automatically in headless environments.
        if pywinauto is None and pyautogui is None:
            self.logger.info("Automation libs missing; skipping gov portal query")
            return None

        try:
            if pywinauto is not None:
                # Best-effort: try to connect to an existing browser window and paste the PIS
                # This is intentionally conservative: only perform actions when the target window is found.
                try:
                    app = pywinauto.Application(backend="uia")
                    # attempt to find a window with title containing 'Conectividade' or 'FGTS'
                    win = None
                    for w in app.windows():
                        title = (w.window_text() or "").lower()
                        if (
                            "conectividade" in title
                            or "fgts" in title
                            or "conecta" in title
                        ):
                            win = w
                            break
                    if win is None:
                        self.logger.info("Conectividade window not found via pywinauto")
                    else:
                        # conservative: do not proceed unless we can find an edit control
                        try:
                            edit = win.child_window(control_type="Edit")
                            edit.set_focus()
                            edit.type_keys(pis_or_cpf, with_spaces=True)
                            # user must press submit manually or further automation implemented per environment
                            self.logger.info(
                                "Pasted PIS/CPF into detected window (no submit)."
                            )
                        except Exception:
                            self.logger.exception("Failed to fill field via pywinauto")
                except Exception:
                    self.logger.exception("pywinauto interaction failed")

            if pyautogui is not None:
                # Fallback: pixel/image-based approach is environment dependent; log and skip by default
                self.logger.info(
                    "pyautogui available but image-based automation disabled by default"
                )

            # We don't actually fetch gov_balance here because UI automation is environment-specific.
            return None
        except Exception:
            self.logger.exception("gov portal automation failed")
            return None

    def process_file(self, path: str) -> None:
        abs_path = os.path.abspath(path)
        file_hash = self._compute_hash(abs_path)
        if self._is_processed(abs_path, file_hash):
            self.logger.debug("Skipping already processed file: %s", abs_path)
            return

        try:
            text = self._extract_text_from_pdf(abs_path)
        except Exception as e:
            reason = str(e)
            self.logger.warning("Failed to open/extract %s: %s", abs_path, reason)
            self._quarantine(abs_path, reason)
            # still mark as processed to avoid endless retries
            try:
                self._mark_processed(abs_path, file_hash)
            except Exception:
                self.logger.exception("Failed to mark quarantined file as processed")
            return

        parsed = self._parse_document(text)

        # determine local balance heuristic: first saldo found
        local_balance = parsed.get("saldos")[0] if parsed.get("saldos") else None

        # Attempt gov query (best-effort, may return None)
        gov_balance = None
        search_id = parsed.get("pis") or parsed.get("cp")
        if search_id:
            try:
                gov_balance = self._query_gov_portal(search_id)
            except Exception:
                self.logger.exception("Gov portal query failed for %s", search_id)

        recon = self._reconcile(local_balance, gov_balance)

        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "funcionario_nome": parsed.get("nome"),
            "pis_encontrado": parsed.get("pis"),
            "cpf_encontrado": parsed.get("cp"),
            "saldo_base": recon.get("local_balance"),
            "gov_balance": recon.get("gov_balance"),
            "dif": recon.get("dif"),
            "status": recon.get("status"),
            "fonte_arquivo": os.path.relpath(abs_path, start=self.root_dir),
            "file_hash": file_hash,
        }

        self._append_log(log_entry)
        self._mark_processed(abs_path, file_hash)
        self.logger.info(
            "Processed %s -> %s",
            abs_path,
            log_entry.get("pis_encontrado") or log_entry.get("cpf_encontrado"),
        )

    def run(self) -> None:
        """Scan the root directory recursively and process PDFs.

        This method is resumable: it will skip files already recorded in the checkpoint store.
        """
        for dirpath, _, filenames in os.walk(self.root_dir):
            for fn in filenames:
                if not fn.lower().endswith(".pd"):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    self.process_file(full)
                except Exception:
                    self.logger.exception("Unhandled error while processing %s", full)

    def resume_from_checkpoint(self, *args, **kwargs) -> None:
        """Public method used by supervisors to resume work.

        It simply calls `run()` since scan is idempotent and checks the checkpoints.
        """
        self.logger.info("Resuming FGTS engine from checkpoint")
        self.run()


if __name__ == "__main__":
    engine = FGTSEngine()
    engine.run()
