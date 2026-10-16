from __future__ import annotations
import re
import io
from typing import Any
from typing import Dict
from typing import List

try:
    import easyocr  # type: ignore[reportMissingImports]
except Exception:  # easyocr optional in scaffold
    easyocr = None

try:
    import spacy  # type: ignore[reportMissingImports]
except Exception:
    spacy = None

    try:
        import pypdf  # type: ignore[reportMissingImports]
    except Exception:
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning)
                import PyPDF2 as pypdf  # type: ignore[reportMissingImports]
        except Exception:
            pypdf = None

try:
    import cv2  # type: ignore[reportMissingImports]
except Exception:
    cv2 = None

try:
    import pytesseract  # type: ignore[reportMissingImports]
except Exception:
    pytesseract = None

try:
    import numpy as np  # type: ignore[reportMissingImports]
except Exception:
    np = None

try:
    from pdf2image import convert_from_bytes  # type: ignore[reportMissingImports]
except Exception:
    convert_from_bytes = None


class DocumentProcessor:
    """Lightweight DocumentProcessor abstraction.

    - Uses EasyOCR + OpenCV when available (optional) for OCR.
    - Uses spaCy NER when available; otherwise falls back to simple regex extraction.
    - Produces per-chunk results (chunks are pages or logical splits).
    """

    def __init__(self):
        self._ocr = None
        self._nlp = None
        if easyocr:
            try:
                self._ocr = easyocr.Reader(["en"], gpu=False)
            except Exception:
                self._ocr = None
        if spacy:
            try:
                # using small model if present; user should install and configure proper model
                self._nlp = spacy.load("en_core_web_sm")
            except Exception:
                self._nlp = None

    async def process(self, data: bytes, filename: str) -> Dict[str, Any]:
        """Process document and return extracted text, entities and chunks.

        The method is permissive: when native libs are missing it returns a reasonable
        placeholder structure so the rest of the pipeline can operate.
        """
        # chunking: if PDF and pypdf available, extract pages
        chunks: List[Dict[str, Any]] = []
        if filename.lower().endswith(".pdf") and pypdf:
            try:
                reader = pypdf.PdfReader(io.BytesIO(data))
                num = len(reader.pages)
                for i in range(num):
                    try:
                        page = reader.pages[i]
                        # try to extract text via PDF page extractor
                        text = page.extract_text() or ""
                    except Exception:
                        text = ""
                    chunks.append({"page": i + 1, "text": text})
            except Exception:
                # Fallback: attempt to render PDF pages to images and OCR them
                if convert_from_bytes and (pytesseract or easyocr) and np is not None:
                    try:
                        images = convert_from_bytes(data)
                        for idx, img in enumerate(images):
                            # convert PIL image to OpenCV BGR
                            arr = np.array(img)
                            if arr.ndim == 3:
                                img_cv = (
                                    cv2.cvtColor(arr, cv2.COLOR_RGB2BGR) if cv2 else arr
                                )
                            else:
                                img_cv = arr
                            text = ""
                            if pytesseract and cv2:
                                try:
                                    text = pytesseract.image_to_string(img_cv)
                                except Exception:
                                    text = ""
                            elif easyocr:
                                try:
                                    reader = easyocr.Reader(["en"], gpu=False)
                                    ocr_res = reader.readtext(arr)
                                    text = " \n ".join([t[1] for t in ocr_res])
                                except Exception:
                                    text = ""
                            chunks.append({"page": idx + 1, "text": text})
                    except Exception:
                        chunks = [
                            {"page": 1, "text": await self._extract_text_plain(data)}
                        ]
                else:
                    chunks = [{"page": 1, "text": await self._extract_text_plain(data)}]
        else:
            chunks = [{"page": 1, "text": await self._extract_text_plain(data)}]

        # run NER if possible
        entities: List[Dict[str, Any]] = []

        # process chunks in parallel (CPU-bound operations delegated to thread)
        async def process_chunk(c: Dict[str, Any]):
            text = c["text"]
            if not text and (cv2 or pytesseract or easyocr):
                # image-based fallback: attempt OCR via pytesseract if available
                if pytesseract and cv2 and np is not None:
                    try:
                        # attempt to render page bytes to image then OCR (best-effort)
                        img = cv2.imdecode(
                            np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR
                        )
                        text = pytesseract.image_to_string(img)
                    except Exception:
                        text = ""
                elif easyocr:
                    try:
                        # easyocr reader expects an image path or array; fallback is skipped
                        text = ""
                    except Exception:
                        text = ""

            if self._nlp and text:
                doc = self._nlp(text)
                ents = []
                for ent in doc.ents:
                    ents.append(
                        {
                            "text": ent.text,
                            "label": ent.label_,
                            "start": ent.start_char,
                            "end": ent.end_char,
                        }
                    )
                c["entities"] = ents
                return ents
            else:
                c["entities"] = self._regex_extract(text)
                return c["entities"]

        import asyncio as _asyncio

        tasks = [_asyncio.create_task(process_chunk(c)) for c in chunks]
        results = await _asyncio.gather(*tasks)
        for ents in results:
            entities.extend(ents)

        # compute rudimentary confidence metric
        ner_confidence = 1.0 if entities else 0.0

        # if confidence < 0.8 provide fallback extraction (already applied via regex)
        fallback_used = ner_confidence < 0.8

        return {
            "filename": filename,
            "chunks": chunks,
            "entities": entities,
            "ner_confidence": ner_confidence,
            "fallback_used": fallback_used,
        }

    async def _extract_text_plain(self, data: bytes) -> str:
        # Best-effort plain text extraction: try simple decode, otherwise empty
        try:
            return data.decode("utf-8")
        except Exception:
            try:
                return data.decode("latin-1")
            except Exception:
                return ""

    def _regex_extract(self, text: str) -> List[Dict[str, Any]]:
        patterns = {
            "cpf": r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
            "cnpj": r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b",
            "number": r"\b\d{4,}\b",
        }
        found = []
        for label, pat in patterns.items():
            for m in re.finditer(pat, text):
                found.append(
                    {
                        "text": m.group(0),
                        "label": label,
                        "start": m.start(),
                        "end": m.end(),
                    }
                )
        return found
