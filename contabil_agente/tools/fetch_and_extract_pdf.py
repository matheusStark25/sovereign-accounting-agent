import sys
from pathlib import Path

import requests
import warnings

# Permit passing the download path as first argument, else fallback to hardcoded
if len(sys.argv) > 1:
    PDF_URL = f"http://127.0.0.1:5000{sys.argv[1]}"
else:
    PDF_URL = "http://127.0.0.1:5000/download/rescisao_5e7ee6ca_1769791533.pd"
OUT_TXT = Path(__file__).parent / "last_extracted_pdf.txt"

try:
    r = requests.get(PDF_URL, timeout=20)
    r.raise_for_status()
except Exception as e:
    print("DOWNLOAD_ERROR", str(e))
    sys.exit(1)

# salvar temporariamente
pdf_path = Path(__file__).parent / "last_downloaded.pd"
with open(pdf_path, "wb") as f:
    f.write(r.content)

# tentar extrair texto com pypdf/PyPDF2
try:
    # Import PdfReader from either the modern 'pypd' package or the older 'PyPDF2'.
    # Use dynamic import to avoid static linter errors when one of the packages
    # is not installed in the environment.
    import importlib

    try:
        try:
            module = importlib.import_module("pypd")
        except Exception:
            # suppress deprecation warnings coming from PyPDF2 if used
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", category=DeprecationWarning, module="PyPDF2"
                )
                module = importlib.import_module("PyPDF2")
        PdfReader = getattr(module, "PdfReader")
    except Exception:
        raise

    reader = PdfReader(str(pdf_path))
    texts = []
    for p in reader.pages:
        try:
            texts.append(p.extract_text() or "")
        except Exception:
            texts.append("")
    full = "\n\n--- PAGE BREAK ---\n\n".join(texts)
    OUT_TXT.write_text(full, encoding="utf-8")
    print("EXTRACTED_TEXT_SAVED", OUT_TXT)
    print(full[:2000])
except Exception as e:
    print("EXTRACT_ERROR", str(e))
    sys.exit(2)
