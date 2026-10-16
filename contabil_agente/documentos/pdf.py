"""PDF dos cálculos, gerado a partir do resultado do motor ``contabil_agente.calc``.

O documento traz: cabeçalho, identificação (se informada), verbas e descontos com a memória de
cálculo, FGTS, tabelas legais usadas, pendências e premissas. No rodapé vai o SHA-256 do resultado
(prova de que o PDF corresponde ao cálculo) e há um bloco de campos de formulário (AcroForm) para
conferência e assinatura: alguns preenchidos e somente leitura, outros editáveis.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from contabil_agente.calc.texto import brl

TITULOS = {
    "rescisao": "Demonstrativo de Rescisão do Contrato de Trabalho",
    "ferias": "Demonstrativo de Férias",
    "decimo_terceiro": "Demonstrativo de 13º Salário",
    "folha": "Holerite / Folha Mensal",
    "inss": "Cálculo de INSS",
    "irrf": "Cálculo de IRRF",
    "fgts": "Cálculo de FGTS",
}
AVISO_LEGAL = (
    "Documento gerado automaticamente a partir do cálculo indicado. Confira os dados e as premissas antes de "
    "usar; não substitui a homologação ou a revisão de um contador."
)
FLAG_READONLY = 1  # bit 1 dos flags de campo de formulário


def _data_br(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(iso) >= 10 and iso[4] == "-" else iso


def hash_do_resultado(resultado: Dict[str, Any]) -> str:
    """SHA-256 do resultado em JSON canônico (chaves ordenadas)."""
    canonico = json.dumps(resultado, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


class _CamposDeAssinatura(Flowable):
    """Campos AcroForm: valores do cálculo (somente leitura) e campos para preencher à mão."""

    def __init__(self, preenchidos: Dict[str, str], largura: float):
        super().__init__()
        self.preenchidos = preenchidos
        self.width = largura
        self.height = 1.0 * cm * (len(preenchidos) + 4)

    def draw(self) -> None:
        form = self.canv.acroForm
        y = self.height - 0.7 * cm
        estilo = dict(borderStyle="solid", borderWidth=0.5, borderColor=colors.grey, fontSize=9, forceBorder=True)
        for nome, valor in self.preenchidos.items():
            self.canv.setFont("Helvetica", 8)
            self.canv.drawString(0, y + 0.55 * cm, nome.replace("_", " ").capitalize())
            ax, ay = self.canv.absolutePosition(0, y - 0.1 * cm)
            form.textfield(
                name=nome, value=valor, x=ax, y=ay, width=self.width * 0.55, height=0.55 * cm,
                fieldFlags="readOnly", **estilo,
            )
            y -= 1.0 * cm
        for nome, rotulo in (
            ("nome_conferente", "Nome de quem conferiu"),
            ("data_conferencia", "Data da conferência"),
            ("assinatura", "Assinatura"),
            ("observacoes", "Observações"),
        ):
            self.canv.setFont("Helvetica", 8)
            self.canv.drawString(0, y + 0.55 * cm, rotulo)
            ax, ay = self.canv.absolutePosition(0, y - 0.1 * cm)
            form.textfield(name=nome, value="", x=ax, y=ay, width=self.width * 0.9, height=0.55 * cm, **estilo)
            y -= 1.0 * cm


def _tabela(linhas: List[List[str]], larguras: List[float], cabecalho: bool = True, valores_a_direita: bool = True) -> Table:
    t = Table(linhas, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    estilo = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT" if valores_a_direita else "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]
    if cabecalho:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF4")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(estilo))
    return t


def _blocos(tipo: str, r: Dict[str, Any], estilo: ParagraphStyle, largura: float) -> List[Any]:
    P = lambda txt: Paragraph(txt, estilo)  # noqa: E731
    cols3 = [largura * 0.58, largura * 0.2, largura * 0.22]
    out: List[Any] = []
    if tipo == "rescisao":
        d = r["datas"]
        out.append(P(f"Admissão {_data_br(d['admissao'])} · Demissão {_data_br(d['demissao'])} · {d['anos_completos']} ano(s) completo(s) · tipo: {r['tipo']}"))
        out.append(Spacer(1, 6))
        linhas = [["Verba", "INSS/IRRF", "Valor"]]
        for v in r["verbas"]:
            inc = ("INSS " if v["incide_inss"] else "") + ("IRRF" if v["incide_irrf"] else "") or "não incide"
            linhas.append([f"{v['descricao']}\n{v['memoria']}", inc, brl(v["valor"])])
        linhas.append(["Total de proventos", "", brl(r["total_proventos"])])
        out += [_tabela(linhas, cols3), Spacer(1, 8)]
        desc = [["Desconto", "", "Valor"]] + [[f"{x['descricao']}\n{x['memoria']}", "", brl(x["valor"])] for x in r["descontos"] if x["valor"]]
        desc.append(["Total de descontos", "", brl(r["total_descontos"])])
        out += [_tabela(desc, cols3), Spacer(1, 8)]
        f = r["fgts"]
        fg = [["FGTS (à parte, pelo empregador)", "", "Valor"], ["Depósito sobre as verbas rescisórias", "", brl(f["deposito_rescisorio"])]]
        if f.get("multa_aliquota"):
            fg.append([f"Multa rescisória de {int(f['multa_aliquota'] * 100)}%", "", brl(f["multa"]) if f.get("multa") is not None else "pendente (informe o saldo)"])
        out += [_tabela(fg, cols3)]
    elif tipo == "ferias":
        linhas = [["Item", "Valor"], ["Valor dos dias", brl(r["valor_dias"])], ["1/3 constitucional", brl(r["terco_constitucional"])]]
        if r["dias_vendidos"]:
            linhas += [["Abono pecuniário", brl(r["abono_pecuniario"])], ["1/3 do abono", brl(r["terco_abono"])]]
        linhas += [["Total bruto", brl(r["total_bruto"])], ["INSS", brl(r["inss"])], ["IRRF", brl(r["irrf"])]]
        out.append(_tabela(linhas, [largura * 0.75, largura * 0.25]))
    elif tipo == "decimo_terceiro":
        linhas = [["Item", "Valor"], [f"13º proporcional ({r['meses']}/12)", brl(r["total_bruto"])],
                  ["1ª parcela (sem descontos)", brl(r["primeira_parcela"])], ["INSS", brl(r["inss"])], ["IRRF", brl(r["irrf"])],
                  ["2ª parcela", brl(r["segunda_parcela"])]]
        out.append(_tabela(linhas, [largura * 0.75, largura * 0.25]))
    elif tipo == "folha":
        linhas = [["Proventos", "Valor"]] + [[k.replace("_", " ").capitalize(), brl(v)] for k, v in r["proventos"].items()]
        linhas.append(["Total de proventos", brl(r["total_proventos"])])
        out += [_tabela(linhas, [largura * 0.75, largura * 0.25]), Spacer(1, 8)]
        desc = [["Descontos", "Valor"]] + [[k.replace("_", " ").upper() if k in ("inss", "irrf") else k.replace("_", " ").capitalize(), brl(v)] for k, v in r["descontos"].items()]
        desc.append(["Total de descontos", brl(r["total_descontos"])])
        out += [_tabela(desc, [largura * 0.75, largura * 0.25]), Spacer(1, 8),
                P(f"FGTS do empregador (informativo, não desconta do empregado): {brl(r['fgts_empregador'])}")]
    elif tipo == "inss":
        linhas = [["Faixa", "Base na faixa", "Alíquota", "Valor"]]
        for p in r["faixas"]:
            linhas.append([f"{brl(p['de'])} a {brl(p['ate'])}", brl(p["base_na_faixa"]), f"{p['aliquota'] * 100:.1f}%", brl(p["valor"])])
        linhas.append(["INSS devido", "", "", brl(r["inss"])])
        out.append(_tabela(linhas, [largura * 0.4, largura * 0.22, largura * 0.14, largura * 0.24]))
    elif tipo == "irrf":
        linhas = [["Item", "Valor"], ["Rendimentos tributáveis", brl(r["rendimentos_tributaveis"])], ["INSS considerado", brl(r["inss_considerado"])],
                  [f"Base de cálculo (dedução: {r['opcao_deducao']})", brl(r["base_calculo"])], ["Imposto pela tabela", brl(r["imposto_tabela"])],
                  ["Redução (Lei 15.270/2025)", brl(r["reducao"])], ["IRRF devido", brl(r["irrf"])]]
        out.append(_tabela(linhas, [largura * 0.75, largura * 0.25]))
    elif tipo == "fgts":
        linhas = [["Item", "Valor"], ["Base", brl(r["base"])], ["Alíquota", f"{r['aliquota'] * 100:.1f}%"], ["Depósito do empregador", brl(r["fgts"])]]
        out.append(_tabela(linhas, [largura * 0.75, largura * 0.25]))
    return out


def _destaque(tipo: str, r: Dict[str, Any]) -> Dict[str, str]:
    """Valores principais que vão para campos de formulário somente leitura."""
    chaves = {
        "rescisao": ("total_proventos", "total_descontos", "total_liquido"),
        "ferias": ("total_bruto", "total_liquido"),
        "decimo_terceiro": ("total_bruto", "total_liquido"),
        "folha": ("total_proventos", "total_descontos", "total_liquido"),
        "inss": ("inss",),
        "irrf": ("irrf",),
        "fgts": ("fgts",),
    }[tipo]
    return {k: brl(r[k]) for k in chaves if k in r}


def gerar_pdf_calculo(
    tipo: str, resultado: Dict[str, Any], contexto: Optional[Dict[str, Any]] = None
) -> bytes:
    """PDF (bytes) do resultado de ``calc.servico.calcular(...)["resultado"]``.

    ``contexto`` aceita ``empresa``, ``nome_funcionario``, ``cpf`` e ``protocolo``; o que faltar fica em branco
    (nada é inventado).
    """
    if tipo not in TITULOS:
        raise ValueError(f"Tipo sem modelo de PDF: {tipo!r}. Use: {', '.join(TITULOS)}.")
    contexto = contexto or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm,
        title=TITULOS[tipo], author="Sovereign Accounting Agent", subject=f"Cálculo de {tipo}",
    )
    largura = A4[0] - 3.6 * cm
    base = getSampleStyleSheet()
    corpo = ParagraphStyle("corpo", parent=base["BodyText"], fontSize=9, leading=12)
    pequeno = ParagraphStyle("pequeno", parent=corpo, fontSize=7.5, leading=10, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", parent=base["Title"], fontSize=15, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base["Heading3"], fontSize=10, spaceBefore=8, spaceAfter=3)
    escapar = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731

    historia: List[Any] = [Paragraph(TITULOS[tipo], h1)]
    ident = [
        ("Empresa", contexto.get("empresa")), ("Funcionário", contexto.get("nome_funcionario")),
        ("CPF", contexto.get("cpf")), ("Protocolo", contexto.get("protocolo")),
    ]
    linhas_ident = [[rotulo, str(valor) if valor else "—"] for rotulo, valor in ident]
    historia += [_tabela(linhas_ident, [largura * 0.2, largura * 0.8], cabecalho=False, valores_a_direita=False), Spacer(1, 6)]

    historia += _blocos(tipo, resultado, corpo, largura)

    liquido = resultado.get("total_liquido")
    if liquido is not None:
        historia += [Spacer(1, 8), Paragraph(f"<b>Líquido a receber: {brl(liquido)}</b>", ParagraphStyle("liq", parent=corpo, fontSize=11))]

    memoria = resultado.get("explicacao") or resultado.get("explanation")
    if memoria:
        historia += [Paragraph("Memória de cálculo", h2)] + [Paragraph("• " + escapar(m), pequeno) for m in memoria]
    if resultado.get("pendencias"):
        historia += [Paragraph("Pendências", h2)] + [Paragraph("• " + escapar(m), corpo) for m in resultado["pendencias"]]
    if resultado.get("avisos"):
        historia += [Paragraph("Premissas", h2)] + [Paragraph("• " + escapar(m), pequeno) for m in resultado["avisos"]]
    tabelas = resultado.get("tabelas") or resultado.get("tabela")
    if tabelas:
        txt = tabelas if isinstance(tabelas, str) else "; ".join(f"{k}: {v}" for k, v in tabelas.items())
        historia += [Paragraph("Tabelas legais usadas", h2), Paragraph(escapar(txt), pequeno)]

    historia += [Paragraph("Conferência e assinatura", h2), _CamposDeAssinatura(_destaque(tipo, resultado), largura * 0.9)]

    digest = hash_do_resultado(resultado)
    emitido = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    def rodape(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(1.8 * cm, 1.15 * cm, f"SHA-256 do cálculo: {digest}")
        canvas.drawString(1.8 * cm, 0.8 * cm, f"Emitido em {emitido}. Gerado automaticamente; confira antes de usar.")
        canvas.drawRightString(A4[0] - 1.8 * cm, 0.8 * cm, f"Página {documento.page}")
        canvas.restoreState()

    doc.build(historia, onFirstPage=rodape, onLaterPages=rodape)
    return buffer.getvalue()
