from __future__ import annotations

import hashlib
import os
from datetime import datetime
from decimal import Decimal, getcontext
from typing import Dict, Any, List, Optional, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

getcontext().prec = 28


class GeradorRelatorioStark:
    """Gera PDF profissional do OrquestradorStark usando ReportLab.

    O gerador é independente do Orquestrador: recebe os dados e retorna
    (filepath, sha256) ou (None, None) em caso de falha.
    """

    def __init__(self, font_path: Optional[str] = None):
        # registra uma fonte padrão se disponível
        try:
            if font_path and os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont("StarkSans", font_path))
                self.header_font = "StarkSans"
            else:
                self.header_font = "Helvetica-Bold"
        except Exception:
            self.header_font = "Helvetica-Bold"

    def _footer_canvas(self, canvas, doc, partial_hash: str):
        canvas.saveState()
        w, h = A4
        footer_text = f"Hash parcial: {partial_hash[:16]}"
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(w / 2.0, 20, footer_text)
        canvas.restoreState()

    def gerar(
        self, dados: Dict[str, Any], output_dir: str, id_empresa: str
    ) -> Tuple[Optional[str], Optional[str]]:
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"RELATORIO_STARK_{ts}_{id_empresa}.pdf"
            path = os.path.join(output_dir or os.getcwd(), fname)

            # build document
            doc = SimpleDocTemplate(
                path,
                pagesize=A4,
                rightMargin=40,
                leftMargin=40,
                topMargin=80,
                bottomMargin=40,
            )
            styles = getSampleStyleSheet()
            story: List = []

            # Header
            title_style = ParagraphStyle(
                "title", parent=styles["Title"], fontName=self.header_font, fontSize=16
            )
            story.append(
                Paragraph("Relatório Stark - Processo de Blindagem", title_style)
            )
            story.append(Spacer(1, 12))

            metadata = dados.get("metadata", {})
            story.append(
                Paragraph(
                    f"Empresa: {metadata.get('empresa_nome', id_empresa)}",
                    styles["Normal"],
                )
            )
            story.append(Paragraph(f"Gerado em: {ts}", styles["Normal"]))
            story.append(Spacer(1, 12))

            # Tabelas: por exemplo, SEFIP
            sefip = dados.get("sefip", {})
            if sefip:
                story.append(Paragraph("SEFIP - Resumo", styles["Heading3"]))
                rows = [["Campo", "Valor"]]
                rows.append(["Processados", str(sefip.get("processed_files", "-"))])
                rows.append(["Erros", str(len(sefip.get("errors", [])))])
                # valor FGTS (se houver) como Decimal
                fgts = sefip.get("fgts_total")
                if fgts is not None:
                    fgts_s = f"R$ {Decimal(str(fgts)):.2f}"
                else:
                    fgts_s = "-"
                rows.append(["Total FGTS", fgts_s])
                t = Table(rows, hAlign="LEFT")
                t.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ]
                    )
                )
                story.append(t)
                story.append(Spacer(1, 12))

            # SINTEGRA
            sintegra = dados.get("sintegra", {})
            if sintegra:
                story.append(Paragraph("SINTEGRA - Resumo", styles["Heading3"]))
                rows = [["Campo", "Valor"]]
                rows.append(["Validados", str(sintegra.get("validated", "-"))])
                rows.append(["Erros", str(len(sintegra.get("errors", [])))])
                t = Table(rows, hAlign="LEFT")
                t.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ]
                    )
                )
                story.append(t)
                story.append(Spacer(1, 12))

            # Auditoria (exibe alguns registros resumidos)
            audit = dados.get("audit", [])
            story.append(Paragraph("Trilha de Auditoria (resumo)", styles["Heading3"]))
            for r in audit[:10]:
                step = r.get("step")
                h = r.get("hash")
                story.append(
                    Paragraph(
                        f"{step} — hash: {h[:12] if h else 'N/A'}", styles["Normal"]
                    )
                )

            story.append(Spacer(1, 20))
            story.append(
                Paragraph("Assinatura Digital de Integridade:", styles["Heading3"])
            )
            story.append(
                Paragraph(
                    "O documento inclui hash parcial no rodapé de cada página.",
                    styles["Normal"],
                )
            )

            partial_hash = (
                audit[-1].get("hash") if audit else hashlib.sha256(b"empty").hexdigest()
            )

            # build
            doc.build(
                story,
                onFirstPage=lambda c, d: self._footer_canvas(c, d, partial_hash),
                onLaterPages=lambda c, d: self._footer_canvas(c, d, partial_hash),
            )

            # compute file hash
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            return path, digest

        except Exception:
            return None, None
