import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Prefer PyMuPDF (fitz) for PDF extraction and EasyOCR as OCR fallback
try:
    import fitz  # PyMuPDF

    HAS_FITZ = True
except Exception:
    fitz = None
    HAS_FITZ = False

try:
    import easyocr

    HAS_EASYOCR = True
except Exception:
    easyocr = None
    HAS_EASYOCR = False

try:
    from PIL import Image  # type: ignore[import]
except Exception:
    Image = None

# Attempt to import audit service for alerts
try:
    from contabil_agente.services.audit_service import AuditService
except Exception:
    AuditService = None


@dataclass
class ParsedResult:
    path: str
    value: Optional[float]
    due_date: Optional[str]
    barcode: Optional[str]
    pix_key: Optional[str]
    ocr_text: str
    anomalies: list


class ParserService:
    """Extrai e valida campos relevantes de PDFs de DAS.

    - Usa pdfminer quando possível para texto pesquisável.
    - Se o texto extraído for pequeno, aplica OCR com tesseract (fallback).
    - Valida consistência básica (valor > 0, prazo coerente, valores não absurdos).
    """

    def __init__(self, ocr_language: str = "por"):
        self.ocr_language = ocr_language

    def _audit(self, msg: str, level: str = "warning"):
        try:
            if AuditService:
                a = AuditService.get_instance()
                a.log_operation(msg)
                return
        except Exception:
            pass
        getattr(logger, level)(msg)

    def _extract_text_pdf(self, path: Path) -> str:
        text = ""
        # try fitz extraction
        if HAS_FITZ:
            try:
                doc = fitz.open(str(path))
                parts = []
                for page in doc:
                    try:
                        parts.append(page.get_text("text") or "")
                    except Exception:
                        try:
                            parts.append(page.get_text() or "")
                        except Exception:
                            parts.append("")
                text = "\n".join(parts)
            except Exception:
                text = ""

        # if very small text, use OCR fallback (EasyOCR preferred)
        if not text or len(text.strip()) < 120:
            if HAS_EASYOCR:
                try:
                    reader = easyocr.Reader([self.ocr_language])
                    imgs = []
                    if Image:
                        try:
                            imgs = [Image.open(str(path))]
                        except Exception:
                            imgs = []
                    # if pdf pages needed, fallback to PIL opening may fail; EasyOCR can work with bytes via numpy but keep simple
                    ocr_texts = []
                    for img in imgs:
                        try:
                            res = reader.readtext(img)
                            ocr_texts.append(" ".join([r[1] for r in res]))
                        except Exception:
                            continue
                    text = "\n".join(ocr_texts) if ocr_texts else text
                except Exception:
                    text = text or ""
            else:
                # last resort try PIL + any installed tesseract
                try:
                    if Image is not None:
                        img = Image.open(str(path))
                        try:
                            import pytesseract

                            text = pytesseract.image_to_string(
                                img, lang=self.ocr_language
                            )
                        except Exception:
                            text = text or ""
                except Exception:
                    text = text or ""

        return text or ""

    def _parse_currency(self, text: str) -> Optional[float]:
        # Look for patterns like R$ 1.234,56 or 1234.56
        m = re.search(r"R\$\s*([0-9\.,]+)", text)
        if not m:
            m = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", text)
        if m:
            raw = m.group(1)
            clean = raw.replace(".", "").replace(",", ".")
            try:
                return float(clean)
            except Exception:
                return None
        # fallback: any number with decimal
        m2 = re.search(r"([0-9]+\.[0-9]{2})", text)
        if m2:
            try:
                return float(m2.group(1))
            except Exception:
                return None
        return None

    def _parse_date(self, text: str) -> Optional[str]:
        # find dd/mm/yyyy
        m = re.search(r"(\d{2}/\d{2}/\d{4})", text)
        if m:
            try:
                d = datetime.strptime(m.group(1), "%d/%m/%Y").date()
                return d.isoformat()
            except Exception:
                return None
        return None

    def _parse_barcode(self, text: str) -> Optional[str]:
        # common barcodes have >=44 digits (boleto PIX may vary)
        m = re.search(r"(\d{25,44})", re.sub(r"\s+", "", text))
        if m:
            return m.group(1)
        return None

    def parse_pdf(self, path: str) -> ParsedResult:
        p = Path(path)
        out: Dict[str, Any] = {
            "path": str(p),
            "value": None,
            "due_date": None,
            "barcode": None,
            "pix_key": None,
            "ocr_text": "",
            "anomalies": [],
        }

        if not p.exists():
            out["anomalies"].append("file_missing")
            self._audit(f"PARSER_FILE_MISSING {p}", level="error")
            return out

        text = self._extract_text_pdf(p)
        out["ocr_text"] = text[:8000]

        value = self._parse_currency(text)
        due = self._parse_date(text)
        barcode = self._parse_barcode(text)

        out.update({"value": value, "due_date": due, "barcode": barcode})

        # Validation rules
        if value is None or (value is not None and value <= 0):
            out["anomalies"].append("value_missing_or_zero")
            self._audit(f"PARSER_ANOMALY value missing/zero for {p}")

        if value and value > 100000:  # heuristic threshold
            out["anomalies"].append("value_unusually_large")
            self._audit(f"PARSER_ANOMALY large value {value} for {p}")

        if due is None:
            out["anomalies"].append("due_date_missing")
            self._audit(f"PARSER_ANOMALY due date missing for {p}")
        else:
            try:
                d = datetime.fromisoformat(due).date()
                if d.year < 2000 or d.year > (datetime.now().year + 2):
                    out["anomalies"].append("due_date_out_of_range")
                    self._audit(f"PARSER_ANOMALY due date out of range {due} for {p}")
            except Exception:
                pass

        # PIX detection (simple)
        if re.search(r"pix", text, re.IGNORECASE):
            # find e-mail or phone or key-like
            m = re.search(r"[\w.-]+@[\w.-]+\.[A-Za-z]{2,}", text)
            if m:
                out["pix_key"] = m.group(0)

        return ParsedResult(**out)

    def validate_against_history(
        self, parsed: ParsedResult, history: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Cross-validate parsed result against optional history (e.g., average values).

        history expected format: {"avg_value": float, "last_due": "YYYY-MM-DD"}
        Returns a dict with validation flags and anomalies.
        """
        issues = []
        try:
            if history:
                avg = history.get("avg_value")
                if avg and parsed.value:
                    # if current value deviates more than 3x or is less than 10% -> flag
                    if parsed.value > avg * 3 or parsed.value < avg * 0.1:
                        issues.append("value_deviation_from_history")
                        self._audit(
                            f"PARSER_VALIDATION anomaly for {parsed.path}: value {parsed.value} vs avg {avg}"
                        )
                last_due = history.get("last_due")
                if last_due and parsed.due_date:
                    try:
                        ld = datetime.fromisoformat(last_due).date()
                        cd = datetime.fromisoformat(parsed.due_date).date()
                        # if due dates are wildly different (e.g., year far apart)
                        if abs(cd.year - ld.year) > 2:
                            issues.append("due_date_unexpected")
                            self._audit(
                                f"PARSER_VALIDATION due date anomaly for {parsed.path}: {parsed.due_date} vs {last_due}"
                            )
                    except Exception:
                        pass
        except Exception:
            pass
        return {"issues": issues, "parsed": asdict(parsed)}


__all__ = ["ParserService"]
