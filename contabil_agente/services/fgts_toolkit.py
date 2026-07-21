import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Optional, Dict, List

from dotenv import load_dotenv

try:
    # Import via importlib to avoid static-analysis false-positives in editors
    import importlib

    pdfplumber = importlib.import_module("pdfplumber")
except Exception:  # pragma: no cover - optional runtime
    pdfplumber = None

try:
    # Import via importlib to avoid static analysis false-positives in editors
    import importlib

    fitz = importlib.import_module("fitz")
except Exception:  # pragma: no cover - optional
    fitz = None

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional
    pd = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
except Exception:  # pragma: no cover - optional
    colors = None


logger = logging.getLogger("FGTS_Toolkit")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


class AuthManager:
    """Zero-trust authentication interface.

    - Loads secrets from environment using python-dotenv.
    - Exposes `get_session_token()` which must be implemented to return a secure token.
    - Provides a placeholder interface for Certificate-based auth (A1/A3). Implementation
      that touches OS keystores must be done by an operator with approved libraries.
    """

    def __init__(self, env_path: Optional[str] = None) -> None:
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()
        self._session_token = None

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return os.getenv(key, default)

    def get_session_token(self) -> str:
        """Return a session token. This implementation reads an encrypted token from env.

        In production, integrate with Windows Cert Store / Smartcard middleware rather than env.
        """
        if self._session_token:
            return self._session_token
        token = self.get_env("FGTS_SESSION_TOKEN")
        if not token:
            raise RuntimeError("Session token not available in environment")
        # In a real zero-trust flow decrypt using local protected keystore here
        self._session_token = token
        return token

    def authenticate_with_certificate(self) -> None:
        """Placeholder for certificate-based auth.

        Implementors should use platform-specific secure APIs (win32crypt, wincertstore,
        or CSP/KSP provider libraries) and must not expose private keys into process logs.
        """
        raise NotImplementedError(
            "Certificate auth must be implemented per environment"
        )


def retry(
    exceptions: tuple = (Exception,),
    tries: int = 4,
    delay: float = 1.0,
    backoff: int = 2,
):
    """Retry decorator with exponential backoff.

    Usage:
        @retry((IOError,), tries=5)
        def fragile():
            ...
    """

    def deco_retry(f: Callable):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    logger.warning(
                        "%s failed with %s; retrying in %.1fs... (%d tries left)",
                        f.__name__,
                        e,
                        mdelay,
                        mtries - 1,
                    )
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry

    return deco_retry


class HybridSeeker:
    """Crawling and data-mining engine for local files and (optionally) web portals.

    - scan_pdfs: recursive scan using pdfplumber or PyMuPDF
    - scan_excels: read xlsx/csv with pandas and validate schema
    """

    PIS_REGEX = re.compile(r"\d{3}\.\d{5}\.\d{2}-\d{1}")
    CPF_REGEX = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")

    def __init__(self, root_dir: str = "./historico_contabil") -> None:
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)

    def _extract_text_pdfplumber(self, path: str) -> str:
        if pdfplumber is None:
            raise RuntimeError("pdfplumber missing")
        parts: List[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)

    def _extract_text_pymupdf(self, path: str) -> str:
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) missing")
        doc = fitz.open(path)
        parts: List[str] = []
        for page in doc:
            parts.append(page.get_text())
        return "\n".join(parts)

    def extract_text(self, path: str) -> str:
        """Try multiple extractors in order to be robust and CPU-friendly."""
        try:
            return self._extract_text_pdfplumber(path)
        except Exception:
            try:
                return self._extract_text_pymupdf(path)
            except Exception:
                logger.exception("Failed to extract text from %s", path)
                return ""

    def scan_pdfs(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for dirpath, _, filenames in os.walk(self.root_dir):
            for fn in filenames:
                if not fn.lower().endswith(".pdf"):
                    continue
                full = os.path.join(dirpath, fn)
                text = self.extract_text(full)
                pis = self.PIS_REGEX.findall(text)
                cpf = self.CPF_REGEX.findall(text)
                results.append(
                    {"path": full, "pis": pis, "cp": cpf, "text_snippet": text[:200]}
                )
        return results

    def scan_excels(self, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
        if pd is None:
            raise RuntimeError("pandas is required to scan excels")
        results: List[Dict[str, Any]] = []
        for dirpath, _, filenames in os.walk(self.root_dir):
            for fn in filenames:
                if not (
                    fn.lower().endswith(".xlsx")
                    or fn.lower().endswith(".xls")
                    or fn.lower().endswith(".csv")
                ):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    df = (
                        pd.read_excel(full)
                        if fn.lower().endswith((".xls", ".xlsx"))
                        else pd.read_csv(full)
                    )
                except Exception:
                    logger.exception("Failed reading spreadsheet %s", full)
                    continue
                # Basic schema validation: ensure required numeric column exists
                col = schema.get("saldo_column", "saldo")
                if col not in df.columns:
                    logger.warning("Missing expected column %s in %s", col, full)
                    continue
                # Coerce numeric
                df[col] = pd.to_numeric(df[col], errors="coerce")
                for _, row in df.iterrows():
                    results.append({"path": full, "row": row.to_dict()})
        return results


class Auditor:
    """Audit trail generator with masking and SHA-256 signing.

    Each query generates a signed JSON entry:
        {timestamp, operator_id, pis_masked, result, signature}
    """

    def __init__(self, operator_id: str, logfile: str = "fgts_audit.jsonl") -> None:
        self.operator_id = operator_id
        self.logfile = os.path.abspath(logfile)

    @staticmethod
    def mask_pis(pis: Optional[str]) -> Optional[str]:
        if not pis:
            return None
        # Keep only last 3 digits visible as '.123.' format per requirement
        digits = re.sub(r"\D", "", pis)
        if len(digits) >= 3:
            return f".{digits[-3:]}."
        return ".***."

    @staticmethod
    def sha256_hex(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def sign_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        payload = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        signature = self.sha256_hex(payload)
        entry_copy = dict(entry)
        entry_copy["signature"] = signature
        return entry_copy

    def log_query(self, pis: Optional[str], result: Dict[str, Any]) -> Dict[str, Any]:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operator_id": self.operator_id,
            "pis_masked": self.mask_pis(pis),
            "result": result,
        }
        signed = self.sign_entry(entry)
        with open(self.logfile, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(signed, ensure_ascii=False) + "\n")
        return signed


class ReportGenerator:
    """Generate a PDF report highlighting divergences using ReportLab."""

    def __init__(self, out_path: str = "fgts_report.pd") -> None:
        self.out_path = out_path

    def generate(self, rows: List[Dict[str, Any]]) -> None:
        if colors is None:
            raise RuntimeError("reportlab required for PDF generation")
        doc = SimpleDocTemplate(self.out_path, pagesize=A4)
        data = [["Nome", "PIS", "Saldo Local", "Saldo Gov", "Status"]]
        for r in rows:
            data.append(
                [
                    r.get("nome"),
                    r.get("pis"),
                    r.get("saldo_local"),
                    r.get("saldo_gov"),
                    r.get("status"),
                ]
            )
        table = Table(data, repeatRows=1)
        style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
        # Highlight divergences in red
        for i, r in enumerate(rows, start=1):
            if r.get("status") == "CRITICAL_DIVERGENCE":
                style.add("BACKGROUND", (0, i), (-1, i), colors.Color(1, 0.8, 0.8))
        table.setStyle(style)
        doc.build([table])


def compare_with_tolerance(
    local: Optional[float], gov: Optional[float], tol: float = 0.01
) -> str:
    try:
        local_v = float(local) if local is not None else 0.0
        gov_v = float(gov) if gov is not None else 0.0
    except Exception:
        return "INVALID"
    if abs(local_v - gov_v) > tol:
        return "CRITICAL_DIVERGENCE"
    return "OK"


if __name__ == "__main__":
    # Example usage
    am = AuthManager()
    seeker = HybridSeeker()
    auditor = Auditor(operator_id=os.getenv("USER", "unknown"))
    results = seeker.scan_pdfs()
    processed = []
    for r in results:
        pis = r.get("pis") and r.get("pis")[0] or None
        # fake gov balance for example
        local = None
        status = "OK"
        entry = {
            "nome": None,
            "pis": pis,
            "saldo_local": local,
            "saldo_gov": None,
            "status": status,
        }
        signed = auditor.log_query(pis, entry)
        processed.append(entry)
    # optionally generate report
    try:
        ReportGenerator().generate(processed)
    except Exception:
        logger.exception("Report generation failed")
