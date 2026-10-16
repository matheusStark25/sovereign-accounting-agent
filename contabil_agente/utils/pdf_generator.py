from __future__ import annotations
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_RIGHT
from decimal import Decimal
from typing import Dict, Optional
from io import BytesIO
from datetime import datetime
from reportlab.pdfgen import canvas




def format_brl(value: Decimal) -> str:
    # Format decimal to Brazilian currency R$ 0.000,00
    q = f"{value:,.2f}"
    # Python uses comma as thousands sep by locale, but here ensure
    return f"R$ {q.replace(',', 'X').replace('.', ',').replace('X', '.')}"


def generate_trct_pdf(payload: Dict[str, object], metadata: Optional[Dict[str, str]] = None) -> bytes:
    """Generate a minimal TRCT PDF using ReportLab and return bytes.

    If `metadata` is provided it will be embedded in the PDF info (Author, Title, Subject).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm)
    styles = getSampleStyleSheet()
    story = []

    title_style = styles["Heading1"]
    story.append(Paragraph("TRCT - Termo de Rescisão", title_style))
    story.append(Spacer(1, 6 * mm))

    normal = styles["Normal"]
    right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT)

    story.append(Paragraph(f"Nome: {payload.get('nome')}", normal))
    story.append(Paragraph(f"ID: {payload.get('id')}", normal))
    story.append(Spacer(1, 4 * mm))

    salario = Decimal(payload.get("salario_base", 0))
    story.append(Paragraph(f"Salário base: {format_brl(salario)}", normal))
    story.append(Paragraph(f"Indenização: {format_brl(Decimal(payload.get('indemnizacao', 0)))}", normal))
    story.append(Paragraph(f"Aviso prévio: {format_brl(Decimal(payload.get('aviso', 0)))}", normal))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(f"Gerado em: {datetime.utcnow().isoformat()} UTC", right))

    def _add_metadata(canvas_obj, doc_obj):
        if not metadata:
            return
        author = metadata.get("author")
        title = metadata.get("title")
        subject = metadata.get("subject")
        if author:
            try:
                canvas_obj.setAuthor(author)
            except Exception:
                pass
        if title:
            try:
                canvas_obj.setTitle(title)
            except Exception:
                pass
        if subject:
            try:
                canvas_obj.setSubject(subject)
            except Exception:
                pass

    doc.build(story, onFirstPage=_add_metadata)
    return buf.getvalue()
