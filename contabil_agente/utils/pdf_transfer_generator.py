"""Gerador de PDF para Aditivo de Transferência de Funcionário."""

from __future__ import annotations
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib import colors
from typing import Dict, Optional
from io import BytesIO
from datetime import datetime
import hashlib
import os
import unicodedata


def generate_transfer_addendum_pdf(
    payload: Dict[str, object], metadata: Optional[Dict[str, str]] = None
) -> Dict[str, object]:
    """Gera PDF de Aditivo de Transferência de Funcionário.

    Args:
        payload: Dicionário com dados do funcionário:
            - nome: Nome completo do funcionário
            - cpf: CPF do funcionário
            - cargo: Cargo atual (opcional)
            - local_origem: Local de trabalho atual (opcional)
            - local_destino: Novo local de trabalho
            - data_transferencia: Data da transferência
            - motivo: Motivo da transferência (opcional)
            - empresa: Nome da empresa (opcional)
            - cnpj: CNPJ da empresa (opcional)
        metadata: Metadados opcionais para o PDF

    Returns:
        Dict com pdf_bytes, pdf_path, sha256, filename
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=25 * mm,
        leftMargin=25 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    story = []

    # Estilos customizados
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
        textColor=colors.HexColor("#1a1a2e"),
    )

    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=12,
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
        textColor=colors.HexColor("#4a4a6a"),
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=11,
        alignment=TA_JUSTIFY,
        spaceAfter=4 * mm,
        leading=16,
    )

    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#666666"),
        spaceAfter=2 * mm,
    )

    value_style = ParagraphStyle(
        "Value",
        parent=styles["Normal"],
        fontSize=11,
        fontName="Helvetica-Bold",
        spaceAfter=4 * mm,
    )

    right_style = ParagraphStyle(
        "Right",
        parent=styles["Normal"],
        fontSize=9,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#888888"),
    )

    # Extrair dados
    nome = payload.get("nome", "Não informado")
    cpf = payload.get("cpf", "Não informado")
    cargo = payload.get("cargo", "Funcionário")
    local_origem = payload.get("local_origem", "Local Atual")
    local_destino = payload.get("local_destino", "Novo Local")
    data_transferencia = payload.get(
        "data_transferencia", datetime.now().strftime("%d/%m/%Y")
    )
    motivo = payload.get("motivo", "Reorganização administrativa")
    empresa = payload.get("empresa", "Empresa Contratante")
    cnpj = payload.get("cnpj", "")

    # Header
    story.append(Paragraph("ADITIVO CONTRATUAL", title_style))
    story.append(Paragraph("Transferência de Local de Trabalho", subtitle_style))
    story.append(Spacer(1, 5 * mm))

    # Identificação da Empresa
    if cnpj:
        story.append(Paragraph(f"<b>{empresa}</b> - CNPJ: {cnpj}", body_style))
    else:
        story.append(Paragraph(f"<b>{empresa}</b>", body_style))
    story.append(Spacer(1, 6 * mm))

    # Corpo do documento
    texto_aditivo = f"""
    Pelo presente instrumento particular, a empresa acima identificada, doravante denominada 
    <b>EMPREGADORA</b>, e o(a) Sr(a). <b>{nome}</b>, portador(a) do CPF nº <b>{cpf}</b>, 
    doravante denominado(a) <b>EMPREGADO(A)</b>, têm entre si justo e acordado o seguinte:
    """
    story.append(Paragraph(texto_aditivo.strip(), body_style))
    story.append(Spacer(1, 6 * mm))

    # CLÁUSULAS
    story.append(Paragraph("<b>CLÁUSULA PRIMEIRA - DO OBJETO</b>", body_style))
    clausula_1 = f"""
    As partes acordam a transferência do local de trabalho do(a) EMPREGADO(A), 
    que passará a exercer suas funções em <b>{local_destino}</b>, a partir de <b>{data_transferencia}</b>.
    """
    story.append(Paragraph(clausula_1.strip(), body_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("<b>CLÁUSULA SEGUNDA - DO LOCAL ANTERIOR</b>", body_style))
    clausula_2 = f"""
    O(A) EMPREGADO(A) exercia anteriormente suas funções em <b>{local_origem}</b>.
    """
    story.append(Paragraph(clausula_2.strip(), body_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("<b>CLÁUSULA TERCEIRA - DA FUNÇÃO</b>", body_style))
    clausula_3 = f"""
    Permanece inalterada a função de <b>{cargo}</b>, bem como todas as demais 
    condições do contrato de trabalho original, especialmente a remuneração.
    """
    story.append(Paragraph(clausula_3.strip(), body_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("<b>CLÁUSULA QUARTA - DO MOTIVO</b>", body_style))
    clausula_4 = f"""
    A presente transferência decorre de: <b>{motivo}</b>.
    """
    story.append(Paragraph(clausula_4.strip(), body_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("<b>CLÁUSULA QUINTA - DAS CONDIÇÕES GERAIS</b>", body_style))
    clausula_5 = """
    Ficam mantidas e ratificadas todas as demais cláusulas do contrato de trabalho 
    que não foram expressamente alteradas pelo presente aditivo.
    """
    story.append(Paragraph(clausula_5.strip(), body_style))
    story.append(Spacer(1, 10 * mm))

    # Data e Local
    data_emissao = datetime.now().strftime("%d de %B de %Y")
    # Traduzir mês para português
    meses = {
        "January": "janeiro",
        "February": "fevereiro",
        "March": "março",
        "April": "abril",
        "May": "maio",
        "June": "junho",
        "July": "julho",
        "August": "agosto",
        "September": "setembro",
        "October": "outubro",
        "November": "novembro",
        "December": "dezembro",
    }
    for en, pt in meses.items():
        data_emissao = data_emissao.replace(en, pt)

    story.append(
        Paragraph(f"<b>Local e Data:</b> _________________, {data_emissao}", body_style)
    )
    story.append(Spacer(1, 15 * mm))

    # Assinaturas
    story.append(Paragraph("_" * 50, body_style))
    story.append(Paragraph(f"<b>EMPREGADORA:</b> {empresa}", body_style))
    story.append(Spacer(1, 15 * mm))

    story.append(Paragraph("_" * 50, body_style))
    story.append(Paragraph(f"<b>EMPREGADO(A):</b> {nome}", body_style))
    story.append(Paragraph(f"CPF: {cpf}", label_style))
    story.append(Spacer(1, 15 * mm))

    # Testemunhas
    story.append(Paragraph("<b>TESTEMUNHAS:</b>", body_style))
    story.append(Spacer(1, 8 * mm))

    story.append(
        Paragraph("1. ___________________________ CPF: _______________", body_style)
    )
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph("2. ___________________________ CPF: _______________", body_style)
    )
    story.append(Spacer(1, 10 * mm))

    # Footer
    timestamp = datetime.utcnow().isoformat()
    story.append(
        Paragraph(f"Documento gerado eletronicamente em: {timestamp} UTC", right_style)
    )

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
    pdf_bytes = buf.getvalue()

    # Gerar hash SHA256
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    # Nome do arquivo
    # Normalize and remove diacritics to produce ASCII-safe filename
    nf = unicodedata.normalize("NFKD", nome)
    ascii_name = nf.encode("ascii", "ignore").decode("ascii")
    nome_safe = (
        "".join(c for c in ascii_name if c.isalnum() or c in " _-")
        .strip()
        .replace(" ", "_")
    )
    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"aditivo_transferencia_{nome_safe}_{timestamp_file}.pdf"

    # Salvar em disco - usar pasta static/downloads para compatibilidade com rota de download
    base_path = os.path.dirname(os.path.dirname(__file__))
    output_dir = os.path.join(base_path, "contabil_agente", "static", "downloads")
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, filename)

    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    return {
        "pdf_bytes": pdf_bytes,
        "pdf_path": pdf_path,
        "sha256": sha256,
        "filename": filename,
        "success": True,
    }
