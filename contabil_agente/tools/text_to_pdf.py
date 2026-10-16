from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

IN_TXT = Path(__file__).parent / "last_extracted_pdf.txt"
OUT_PDF = Path(__file__).parent.parent / "temp_docs" / "rescisao_printable_clean.pd"
OUT_PDF.parent.mkdir(parents=True, exist_ok=True)

# Registrar fonte padrão (usar DejaVu Sans se disponível para acentuação)
try:
    pdfmetrics.registerFont(TTFont("DejaVuSans", "DejaVuSans.tt"))
    FONT_NAME = "DejaVuSans"
except Exception:
    FONT_NAME = "Helvetica"

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 20 * mm
LINE_HEIGHT = 11

with open(IN_TXT, "r", encoding="utf-8") as f:
    lines = [ln.rstrip() for ln in f]

c = canvas.Canvas(str(OUT_PDF), pagesize=A4)
c.setFont(FONT_NAME, 11)

x = MARGIN
y = PAGE_HEIGHT - MARGIN

for line in lines:
    if y < MARGIN + LINE_HEIGHT:
        c.showPage()
        c.setFont(FONT_NAME, 11)
        y = PAGE_HEIGHT - MARGIN
    # If the line is very long, wrap manually
    if len(line) > 120:
        # naive wrap at 120 chars
        while len(line) > 0:
            part = line[:120]
            c.drawString(x, y, part)
            line = line[120:]
            y -= LINE_HEIGHT
            if y < MARGIN + LINE_HEIGHT:
                c.showPage()
                c.setFont(FONT_NAME, 11)
                y = PAGE_HEIGHT - MARGIN
    else:
        c.drawString(x, y, line)
        y -= LINE_HEIGHT

c.save()
print("PDF_CREATED", OUT_PDF)
