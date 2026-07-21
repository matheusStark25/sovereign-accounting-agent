"""
DocumentService - Geração de documentos PDF profissionais
Encapsula toda lógica de criação de formulários e relatórios
"""

import importlib
import json
import logging
import os
import re
import tempfile
import threading
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional
import time
import uuid
from queue import Queue

# Optional heavy deps: reportlab, pypdf / PyPDF2
HAS_REPORTLAB = True
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except Exception:
    HAS_REPORTLAB = False

HAS_PYPDF2 = False
PdfReader = None
PdfWriter = None
try:
    _pypdf = importlib.import_module("pypd")
    PdfReader = _pypdf.PdfReader
    PdfWriter = _pypdf.PdfWriter
    HAS_PYPDF2 = True
except Exception:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyPDF2")
        try:
            _pyPdf2 = importlib.import_module("PyPDF2")
            PdfReader = _pyPdf2.PdfReader
            PdfWriter = _pyPdf2.PdfWriter
            HAS_PYPDF2 = True
        except Exception:
            HAS_PYPDF2 = False

# Optional tool
HAS_TOOLCALC = True
try:
    from tools.calculo import ToolCalculo
except Exception:
    HAS_TOOLCALC = False

logger = logging.getLogger(__name__)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(ch)
    logger.setLevel(logging.INFO)


# Defaults (replacing AppConfig usage)
DEFAULT_MAX_FILENAME_LENGTH = 255
DEFAULT_OUTPUT_FILENAME = "documento.pd"


@dataclass
class DocumentConfig:
    output_folder: Optional[str] = None
    max_filename_length: int = DEFAULT_MAX_FILENAME_LENGTH
    allow_pdf: bool = True
    memory_only: bool = False
    extra: dict = field(default_factory=dict)


class DocumentService:
    """
    Serviço de geração de documentos. Projeto para operar mesmo sem
    bibliotecas externas, com modos de compatibilidade e geração apenas de
    dados estruturados (JSON/Dict) quando necessário.
    """

    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls, config: Optional[Dict] = None):
        """Lazy-initialized singleton accessor."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cfg = DocumentConfig(**(config or {}))
                    cls._instance = cls(cfg)
        return cls._instance

    def __init__(self, config: Optional[DocumentConfig] = None):
        # allow direct instantiation with dict too
        if isinstance(config, dict):
            config = DocumentConfig(**config)
        self.config = config or DocumentConfig()

        # ToolCalculo optional
        self.calculadora = ToolCalculo() if HAS_TOOLCALC else None
        if not HAS_TOOLCALC:
            logger.warning(
                json.dumps(
                    {"fallback": "toolcalculo_missing", "action": "basic_calc_or_none"}
                )
            )

        # Resolve output folder: param -> ENV -> user home -> tempfile
        out_folder = self.config.output_folder or os.environ.get("DOCS_OUTPUT_PATH")
        if not out_folder:
            # Prefer workspace-local temp_docs if present (keeps compatibility with legacy code)
            try:
                pkg_root = Path(__file__).resolve().parents[1]
                local_temp = pkg_root / "temp_docs"
                if not local_temp.exists():
                    # try to create it; if creation fails, fallback continues
                    local_temp.mkdir(parents=True, exist_ok=True)
                out_folder = str(local_temp)
            except Exception:
                out_folder = None
        # If out_folder still not set, fallback to user home or tmpdir
        if not out_folder:
            try:
                out_folder = str(Path.home())
            except Exception:
                out_folder = tempfile.gettempdir()

        # Final fallback to tempdir
        if not out_folder:
            out_folder = tempfile.gettempdir()

        # Ensure writable
        self.output_folder = self._ensure_output_folder(out_folder)

        # Document titles
        self.document_titles = {
            "rescisao": "TERMO DE RESCISÃO CONTRATUAL",
            "ferias": "FORMULÁRIO DE FÉRIAS",
            "decimo_terceiro": "FORMULÁRIO DE 13º SALÁRIO",
            "folha_pagamento": "FORMULÁRIO DE FOLHA DE PAGAMENTO",
            "impostos": "FORMULÁRIO DE APURAÇÃO DE IMPOSTOS",
            "inss": "FORMULÁRIO DE INSS",
            "fgts": "FORMULÁRIO DE FGTS",
            "admissao": "FORMULÁRIO DE ADMISSÃO",
            "transferencia": "ADITIVO DE TRANSFERÊNCIA DE LOCAL DE TRABALHO",
            "consulta": "DOCUMENTO DE ORIENTAÇÃO CONTÁBIL",
        }

    def sanitize_filename(self, filename: str) -> Optional[str]:
        """Sanitiza nome de arquivo para evitar path traversal"""
        if not filename:
            return None

        filename = os.path.basename(filename)
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

        if len(filename) > self.config.max_filename_length:
            name, ext = os.path.splitext(filename)
            filename = name[: self.config.max_filename_length - len(ext)] + ext

        return filename if filename else None

    def _ensure_output_folder(self, folder_path: str) -> str:
        """
        Ensure the output folder exists and is writable. Returns a valid folder path.
        Falls back to a temporary directory on failure.
        """
        try:
            p = Path(folder_path)
            # Expand user and resolve relative paths
            try:
                p = Path(os.path.expanduser(str(p))).resolve()
            except Exception:
                p = Path(folder_path)

            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)

            # Verify write permission by attempting to create a temp file
            test_file = p / (".writetest_%d" % os.getpid())
            try:
                with open(test_file, "w"):
                    pass
                test_file.unlink(missing_ok=True)
                return str(p)
            except Exception:
                logger.warning(
                    json.dumps(
                        {"warning": "output_folder_not_writable", "path": str(p)}
                    )
                )
        except Exception:
            logger.exception("Erro ao garantir pasta de saída; usando tempdir")

        # Fallback to system tempdir
        tmp = tempfile.gettempdir()
        try:
            return str(Path(tmp).resolve())
        except Exception:
            return tmp

    def should_generate_pdf(self, user_message: str, ai_response: str) -> bool:
        """
        Determina se deve gerar PDF automaticamente
        Atualmente desabilitado - só gera com marcador explícito
        """
        # Verificar marcador manual na resposta da IA
        if "[DOCUMENTO_OFICIAL]" in (ai_response or ""):
            return True

        # Normalizar e remover acentos para detecção robusta
        try:
            import unicodedata

            def _normalize(text: str) -> str:
                if not text:
                    return ""
                nfkd = unicodedata.normalize("NFD", text)
                return "".join(
                    [c for c in nfkd if unicodedata.category(c) != "Mn"]
                ).lower()

        except Exception:

            def _normalize(text: str) -> str:
                return (text or "").lower()

        user_norm = _normalize(user_message or "")
        ai_norm = _normalize(ai_response or "")

        # Detectar comandos explícitos do usuário solicitando geração de documento/pdf
        patterns = [
            r"\b(gerar|gere|criar|emitir|geracao)\b.*\b(documento|pdf|aditivo|contrato|formulario|formulário)\b",
            r"\b(documento|pdf|aditivo|contrato|formulario|formulário)\b.*\b(gerar|gere|criar|emitir)\b",
        ]

        for p in patterns:
            if re.search(p, user_norm):
                return True

        # Fallback: se a IA incluiu um sumário executivo, considerar gerar
        if "[sumario_executivo]" in ai_norm or "sumario executivo" in ai_norm:
            return True

        return False

    def _extract_data_from_content(self, content: str, metadata: Dict = None) -> Dict:
        """Extrai dados estruturados do conteúdo e metadata"""
        dados = {}

        # Extrair do metadata primeiro
        if metadata:
            session_context = metadata.get("session_context", {})
            dados.update(session_context)

        # Normalizar conteúdo para facilitar extração
        content_norm = content.lower()

        # Extrair do conteúdo usando regex
        # Nome - procurar por padrão de nome (duas palavras capitalizadas ou minúsculas sequenciais)
        # Ex: "ramiro santos", "João Silva", "raimor alvez"
        # Priorizar nomes com mais de 4 letras cada palavra para evitar "certo sim"
        palavras = content.split()
        palavras_comuns = {
            "posto",
            "para",
            "agora",
            "cp",
            "data",
            "janeiro",
            "fevereiro",
            "março",
            "abril",
            "maio",
            "junho",
            "julho",
            "agosto",
            "setembro",
            "outubro",
            "novembro",
            "dezembro",
            "são",
            "de",
            "do",
            "da",
            "meu",
            "funcionario",
            "funcionário",
            "ser",
            "via",
            "bom",
            "boa",
            "dia",
            "tarde",
            "noite",
            "gasolina",
            "transferido",
            "outro",
            "que",
            "preciso",
            "enho",
            "ter",
            "trnsferiodo",
            "deum",
            "pra",
            "certo",  # Adicionar "certo" e "sim" para evitar capturá-los como nome
            "sim",
        }

        # Primeira passagem: procurar nomes com palavras longas (>4 letras)
        for i in range(len(palavras) - 1):
            palavra1 = palavras[i].strip(",.!?;")
            palavra2 = palavras[i + 1].strip(",.!?;")

            if (
                len(palavra1) > 4
                and len(palavra2) > 4
                and palavra1.lower() not in palavras_comuns
                and palavra2.lower() not in palavras_comuns
                and palavra1[0].isalpha()
                and palavra2[0].isalpha()
                and not palavra1.isdigit()
                and not palavra2.isdigit()
            ):
                # Verificar se não é parte de "posto X"
                if i == 0 or palavras[i - 1].lower() not in [
                    "posto",
                    "de",
                    "do",
                    "psoto",
                ]:
                    possivel_nome = f"{palavra1} {palavra2}".title()
                    dados["nome"] = possivel_nome
                    logger.info(f"Nome encontrado (prioridade): {dados['nome']}")
                    break

        # Segunda passagem: se não encontrou, aceitar nomes mais curtos (>2 letras)
        if "nome" not in dados:
            for i in range(len(palavras) - 1):
                palavra1 = palavras[i].strip(",.!?;")
                palavra2 = palavras[i + 1].strip(",.!?;")

                if (
                    len(palavra1) > 2
                    and len(palavra2) > 2
                    and palavra1.lower() not in palavras_comuns
                    and palavra2.lower() not in palavras_comuns
                    and palavra1[0].isalpha()
                    and palavra2[0].isalpha()
                    and not palavra1.isdigit()
                    and not palavra2.isdigit()
                ):
                    # Verificar se não é parte de "posto X"
                    if i == 0 or palavras[i - 1].lower() not in [
                        "posto",
                        "de",
                        "do",
                        "psoto",
                    ]:
                        possivel_nome = f"{palavra1} {palavra2}".title()
                        dados["nome"] = possivel_nome
                        logger.info(f"Nome encontrado (fallback): {dados['nome']}")
                        break

        # CPF - qualquer sequência de 8-11 dígitos
        cpf_match = re.search(r"\b(\d{8,11})\b", content)
        if cpf_match:
            cpf_raw = cpf_match.group(1)
            # Formatar CPF
            if len(cpf_raw) == 11:
                dados["cp"] = (
                    f"{cpf_raw[:3]}.{cpf_raw[3:6]}.{cpf_raw[6:9]}-{cpf_raw[9:]}"
                )
            elif len(cpf_raw) == 8:
                # CPF sem os últimos dígitos - comum em conversas informais
                dados["cp"] = cpf_raw
            else:
                dados["cpf"] = cpf_raw

        # Datas - padrões brasileiros
        meses = {
            "janeiro": "01",
            "fevereiro": "02",
            "março": "03",
            "marco": "03",
            "abril": "04",
            "maio": "05",
            "junho": "06",
            "julho": "07",
            "agosto": "08",
            "setembro": "09",
            "outubro": "10",
            "novembro": "11",
            "dezembro": "12",
        }

        data_match = re.search(
            r"(\d{1,2})\s+(?:de\s+|e\s+)?(janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)",
            content,
            re.IGNORECASE,
        )
        if data_match:
            dia = data_match.group(1)
            mes_nome = data_match.group(2).lower()
            mes = meses.get(mes_nome, "01")
            ano = datetime.now().year
            dados["data_transferencia"] = f"{dia.zfill(2)}/{mes}/{ano}"

        # Postos - buscar padrões específicos melhorados
        # Exemplo: "posto galosian agora jorge soa jose"
        # ou "psoto jorge soa jose" (com erro de digitação)
        # ou "do posto jorge soa jose"
        # Atual = palavra após "posto/psoto" e antes de conectores
        # Novo = tudo após conectores (para/agora/pra) até número/data

        # Posto atual - padrão: "posto/psoto X" ou "de/do posto/psoto X"
        posto_atual_patterns = [
            r"(?:de|do)?\s*p[os]?[os]to\s+(?:de\s+)?(\w+)\s+(?:para|pra|agora)",  # posto/psoto (de) X para/pra/agora
            r"transferi\w*\s+(?:de|do)?\s*(?:um)?\s*p[os]?[os]to\s+(?:de\s+)?(\w+)",  # transferido de/do posto/psoto X
            r"deum\s+p[os]?[os]to\s+(?:de\s+)?(\w+)",  # deum posto (de) X
        ]

        for pattern in posto_atual_patterns:
            match = re.search(pattern, content_norm)
            if match:
                posto = match.group(1).strip()
                if (
                    posto
                    and len(posto) > 2
                    and posto
                    not in ["vai", "ser", "esta", "está", "o", "a", "que", "outro"]
                ):
                    dados["posto_atual"] = f"Posto {posto.title()}"
                    logger.info(f"Posto atual encontrado: {dados['posto_atual']}")
                    break

        # Posto novo - buscar após conectores (para/pra/agora) até número ou pontuação
        # Capturar múltiplas palavras: "jorge soa jose"
        # Considerar erros de digitação: "psoto jorge soa jose"
        # Parar em certas palavras-chave: "do", "eu", "preciso", etc
        posto_novo_patterns = [
            r"(?:para|pra)\s+outro\s+(?:p[os]?[os]to\s+)?(?:do\s+)?([a-z\s]{3,40}?)\s+(?:do\s+eu|eu\s+|preciso|boa\s+|tarde|gere|pdf)",
            r"p[os]?[os]to\s+([a-z\s]{3,30}?)\s+\d{1,2}\s+de",  # posto/psoto X DD de (seguido de data)
        ]

        for pattern in posto_novo_patterns:
            match = re.search(pattern, content_norm)
            if match:
                posto = match.group(1).strip()
                # Remover palavras indesejadas no final (mas não "soa" que pode fazer parte do nome)
                posto = re.sub(
                    r"\b(do|da|que|eu|o|a|outro|enho|um|ter|vai|ser)\b.*$",
                    "",
                    posto,
                    flags=re.IGNORECASE,
                ).strip()
                # Limpar espaços extras
                posto = " ".join(posto.split())
                if posto and len(posto) > 2:
                    dados["posto_novo"] = f"Posto {posto.title()}"
                    logger.info(f"Posto novo encontrado: {dados['posto_novo']}")
                    break

        logger.info(f"📊 Dados extraídos: {dados}")
        return dados

    def generate_structured_data(self, content: str, metadata: Dict = None) -> Dict:
        """Public API to extract structured data without generating PDF."""
        try:
            return self._extract_data_from_content(content, metadata)
        except Exception:
            logger.exception("Falha ao extrair dados; retornando vazio")
            return {}

    def generate_professional_pdf(
        self, filename: str, content: str, metadata: Dict = None
    ) -> bool:
        """
        Gera PDF profissional preenchido com dados da conversa

        Args:
            filename: Nome do arquivo PDF
            content: Conteúdo/orientações do documento
            metadata: Metadados (cliente, protocolo, data, tipo, session_context, etc)

        Returns:
            True se gerado com sucesso, False caso contrário
        """
        safe_name = self.sanitize_filename(filename)
        if not safe_name:
            logger.error("Nome de arquivo inválido")
            return False

        filepath = os.path.join(self.output_folder, safe_name)

        # If PDFs are not available or allowed, fall back to structured output
        if not HAS_REPORTLAB or not HAS_PYPDF2 or not self.config.allow_pdf:
            logger.warning(
                json.dumps(
                    {
                        "fallback": "pdf_generation_disabled",
                        "has_reportlab": HAS_REPORTLAB,
                        "has_pypdf2": HAS_PYPDF2,
                        "allow_pdf": self.config.allow_pdf,
                    }
                )
            )
            # produce structured JSON file as fallback
            dados_extraidos = self._extract_data_from_content(content, metadata)
            out = {
                "filename": safe_name,
                "dados": dados_extraidos,
                "metadata": metadata,
            }
            try:
                with open(filepath + ".json", "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=2)
                return True
            except Exception:
                logger.exception("Falha ao escrever fallback JSON para documento")
                return False

        try:
            # Extrair dados da conversa
            dados_extraidos = self._extract_data_from_content(content, metadata)
            logger.info("Dados extraídos para PDF: %s", dados_extraidos)

            # Detectar tipo de documento
            doc_type = (
                metadata.get("tipo_documento", "consulta") if metadata else "consulta"
            )

            # Detectar se é transferência
            if "posto_atual" in dados_extraidos or "transferi" in content.lower():
                doc_type = "transferencia"

            # Configurar documento
            pdf_doc = SimpleDocTemplate(
                filepath,
                pagesize=A4,
                rightMargin=60,
                leftMargin=60,
                topMargin=50,
                bottomMargin=50,
            )

            styles = getSampleStyleSheet()
            story = []

            # === ESTILOS CUSTOMIZADOS ===
            titulo_style = ParagraphStyle(
                "TituloFormulario",
                parent=styles["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=16,
                alignment=1,
                spaceAfter=8,
                textColor=colors.HexColor("#1a1a1a"),
            )

            subtitulo_style = ParagraphStyle(
                "SubtituloFormulario",
                parent=styles["Normal"],
                fontName="Helvetica",
                fontSize=10,
                alignment=1,
                spaceAfter=20,
                textColor=colors.HexColor("#666666"),
            )

            label_style = ParagraphStyle(
                "LabelCampo",
                parent=styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=9,
                textColor=colors.HexColor("#333333"),
            )

            # === CABEÇALHO ===
            titulo = self.document_titles.get(doc_type, "DOCUMENTO CONTÁBIL")
            story.append(Paragraph(titulo, titulo_style))
            story.append(
                Paragraph("Elite Sênior Consultoria Contábil", subtitulo_style)
            )

            # Linha divisória
            tabela_linha = Table([["", ""]], colWidths=[pdf_doc.width])
            tabela_linha.setStyle(
                TableStyle(
                    [
                        ("LINEABOVE", (0, 0), (-1, 0), 1.5, colors.HexColor("#2dce89")),
                    ]
                )
            )
            story.append(tabela_linha)
            story.append(Spacer(1, 15))

            # === METADADOS ===
            if metadata:
                meta_style = styles["Normal"]
                meta_style.fontSize = 10
                meta_style.leading = 14

                cliente = metadata.get("cliente", "Consulta Online")
                protocolo = metadata.get("protocolo", "N/A")
                data = datetime.now().strftime("%d/%m/%Y às %H:%M")
                pergunta = metadata.get("pergunta_usuario", "")

                # Para documentos formais (transferência, rescisão, etc), não exibir consulta original
                documentos_formais = [
                    "transferencia",
                    "rescisao",
                    "ferias",
                    "decimo_terceiro",
                    "admissao",
                ]

                meta_html = f"""
                <b>INFORMAÇÕES DO DOCUMENTO</b><br/>
                <br/>
                <b>Cliente:</b> {cliente}<br/>
                <b>Data de Emissão:</b> {data}<br/>
                <b>Protocolo:</b> {protocolo}<br/>
                """

                # Exibir consulta original apenas para documentos informativos (não formais)
                if pergunta and doc_type not in documentos_formais:
                    pergunta_limpa = pergunta.replace("<", "&lt;").replace(">", "&gt;")
                    meta_html += f"<b>Consulta Original:</b> {pergunta_limpa}<br/>"

                story.append(Paragraph(meta_html, meta_style))
                story.append(Spacer(1, 20))
                story.append(
                    Paragraph("<hr width='100%' color='#cccccc'/>", styles["Normal"])
                )
                story.append(Spacer(1, 20))

            # === CONTEÚDO - Personalizado por tipo de documento ===
            section_title = ParagraphStyle(
                "SectionTitle",
                parent=styles["Heading3"],
                fontName="Helvetica-Bold",
                fontSize=12,
                spaceAfter=10,
                textColor=colors.HexColor("#2dce89"),
            )

            content_style = ParagraphStyle(
                "Content",
                parent=styles["BodyText"],
                fontName="Helvetica",
                fontSize=11,
                leading=16,
                alignment=4,  # Justificado
            )

            # Para transferência, criar conteúdo específico
            if doc_type == "transferencia":
                story.append(Paragraph("TERMO DE TRANSFERÊNCIA", section_title))
                story.append(Spacer(1, 10))

                nome_func = dados_extraidos.get("nome", "_______________")
                cpf_func = dados_extraidos.get("cp", "_______________")
                posto_de = dados_extraidos.get("posto_atual", "_______________")
                posto_para = dados_extraidos.get("posto_novo", "_______________")
                data_transf = dados_extraidos.get(
                    "data_transferencia", datetime.now().strftime("%d/%m/%Y")
                )

                conteudo_transferencia = f"""
                <b>1. IDENTIFICAÇÃO DO FUNCIONÁRIO</b><br/>
                Nome: {nome_func}<br/>
                CPF: {cpf_func}<br/>
                <br/>
                <b>2. DETALHES DA TRANSFERÊNCIA</b><br/>
                O funcionário acima identificado será transferido conforme especificado:<br/>
                <br/>
                <b>De:</b> {posto_de}<br/>
                <b>Para:</b> {posto_para}<br/>
                <b>Data de Vigência:</b> {data_transf}<br/>
                <br/>
                <b>3. CONDIÇÕES</b><br/>
                &bull; A transferência não implica alteração salarial;<br/>
                &bull; Mantém-se todas as demais cláusulas do contrato de trabalho;<br/>
                &bull; O funcionário deverá se apresentar no novo local a partir da data especificada;<br/>
                &bull; Todas as despesas com a transferência serão de responsabilidade do empregador.<br/>
                <br/>
                <b>4. OBSERVAÇÕES</b><br/>
                Este aditivo contratual é parte integrante do contrato de trabalho vigente.
                """

                story.append(Paragraph(conteudo_transferencia, content_style))
                story.append(Spacer(1, 15))
            else:
                # Conteúdo genérico para outros tipos
                story.append(Paragraph("ANÁLISE TÉCNICA E ORIENTAÇÕES", section_title))
                story.append(Spacer(1, 10))

                # Limpar marcadores de controle
                content_clean = re.sub(r"\[DOCUMENTO_OFICIAL\]", "", content)
                content_clean = re.sub(r"\[SUMÁRIO_EXECUTIVO\]", "", content_clean)
                content_clean = re.sub(r"\[FIM_SUMÁRIO\]", "", content_clean)
                content_clean = re.sub(
                    r"<pensamento>.*?</pensamento>", "", content_clean, flags=re.DOTALL
                )

                # Processar parágrafos
                paragraphs = content_clean.split("\n\n")
                for para in paragraphs:
                    para = para.strip()
                    if para:
                        # Detectar títulos (terminam com :)
                        if para.endswith(":") and len(para) < 100:
                            section_h4 = ParagraphStyle(
                                "SectionH4",
                                parent=styles["Heading4"],
                                fontName="Helvetica-Bold",
                                fontSize=11,
                                spaceAfter=6,
                                spaceBefore=12,
                            )
                            story.append(Paragraph(para, section_h4))
                        else:
                            # Formatação markdown
                            formatted = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", para)
                            formatted = re.sub(r"\*(.*?)\*", r"<i>\1</i>", formatted)

                            # Bullet points
                            if para.startswith("•"):
                                formatted = "&bull; " + formatted.lstrip("•").lstrip()
                            elif para.startswith("-"):
                                formatted = "&bull; " + formatted.lstrip("-").lstrip()

                            formatted = formatted.replace("\\n", "<br/>")
                            story.append(Paragraph(formatted, content_style))
                            story.append(Spacer(1, 8))

            # === CAMPOS ADICIONAIS (apenas se não for transferência) ===
            if doc_type != "transferencia":
                story.append(Spacer(1, 20))
                story.append(
                    Paragraph("<b>DADOS DO COLABORADOR/BENEFICIÁRIO</b>", label_style)
                )
                story.append(Spacer(1, 10))

                nome_display = dados_extraidos.get("nome", "_" * 50)
                cpf_display = dados_extraidos.get("cp", "_" * 20)

                campos_dados = [
                    ["Nome Completo:", nome_display],
                    ["CPF:", cpf_display, "RG:", "_" * 20],
                    ["Data de Nascimento:", "_" * 18, "Data de Admissão:", "_" * 18],
                    ["Cargo/Função:", "_" * 70],
                    ["Salário Base:", "R$ _____________", "CBO:", "_____________"],
                ]

                tabela_dados = Table(
                    campos_dados, colWidths=[4 * cm, 6 * cm, 2.5 * cm, 3.5 * cm]
                )
                tabela_dados.setStyle(
                    TableStyle(
                        [
                            ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                            ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 9),
                            ("FONT", (1, 0), (-1, -1), "Helvetica", 9),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ]
                    )
                )
                story.append(tabela_dados)
                story.append(Spacer(1, 20))

                # === CÁLCULOS (apenas para documentos financeiros) ===
                if doc_type in [
                    "ferias",
                    "rescisao",
                    "decimo_terceiro",
                    "folha_pagamento",
                ]:
                    story.append(Paragraph("<b>CÁLCULOS E VALORES</b>", label_style))
                    story.append(Spacer(1, 10))

                    # CALCULAR VALORES REAIS usando Tool_Calculo
                    valores_calculados = self._calcular_valores_documento(
                        doc_type, dados_extraidos, metadata
                    )

                    # Montar tabela com VALORES REAIS
                    campos_calculos = [["Descrição", "Valor (R$)", "Observações"]]

                    if valores_calculados:
                        for item in valores_calculados.get("itens", []):
                            campos_calculos.append(
                                [
                                    item.get("descricao", ""),
                                    f"R$ {item.get('valor', 0):,.2f}".replace(",", "X")
                                    .replace(".", ",")
                                    .replace("X", "."),
                                    item.get("obs", ""),
                                ]
                            )

                        # Linha de total
                        total = valores_calculados.get("total_liquido", 0)
                        campos_calculos.append(
                            [
                                "TOTAL LÍQUIDO:",
                                f"R$ {total:,.2f}".replace(",", "X")
                                .replace(".", ",")
                                .replace("X", "."),
                                "",
                            ]
                        )
                    else:
                        # Fallback: linhas vazias se não conseguir calcular
                        for _ in range(5):
                            campos_calculos.append(["_" * 40, "_" * 20, "_" * 30])
                        campos_calculos.append(["TOTAL:", "_" * 20, ""])

                    tabela_calculos = Table(
                        campos_calculos, colWidths=[7 * cm, 4 * cm, 5 * cm]
                    )
                    tabela_calculos.setStyle(
                        TableStyle(
                            [
                                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                                ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
                                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    colors.HexColor("#e8e8e8"),
                                ),
                                (
                                    "BACKGROUND",
                                    (0, -1),
                                    (0, -1),
                                    colors.HexColor("#f0f0f0"),
                                ),
                                ("FONT", (0, -1), (1, -1), "Helvetica-Bold", 10),
                            ]
                        )
                    )
                    story.append(tabela_calculos)
                    story.append(Spacer(1, 20))

                # === OBSERVAÇÕES ===
                story.append(Paragraph("<b>OBSERVAÇÕES IMPORTANTES</b>", label_style))
                story.append(Spacer(1, 8))

                for _ in range(3):
                    story.append(Paragraph("_" * 100, styles["Normal"]))
                    story.append(Spacer(1, 8))
            else:
                # Para transferência, apenas pequena área de observações
                story.append(Spacer(1, 15))
                story.append(Paragraph("<b>OBSERVAÇÕES ADICIONAIS</b>", label_style))
                story.append(Spacer(1, 8))
                story.append(Paragraph("_" * 100, styles["Normal"]))
                story.append(Spacer(1, 8))
                story.append(Paragraph("_" * 100, styles["Normal"]))
                story.append(Spacer(1, 8))

            # === ASSINATURAS ===
            story.append(Spacer(1, 25))

            assinaturas_data = [
                ["", "", ""],
                ["_" * 35, "_" * 35, "_" * 35],
                [
                    "Responsável pelo Preenchimento",
                    "Contador(a) Responsável",
                    "Autorização/Visto",
                ],
                ["Nome:", "CRC:", "Data:"],
                ["CPF:", "Data:", "Carimbo:"],
            ]

            tabela_assinaturas = Table(
                assinaturas_data, colWidths=[5.5 * cm, 5.5 * cm, 5.5 * cm]
            )
            tabela_assinaturas.setStyle(
                TableStyle(
                    [
                        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                        ("FONT", (0, 2), (-1, 2), "Helvetica-Bold", 8),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LINEABOVE", (0, 1), (-1, 1), 1, colors.black),
                        ("TOPPADDING", (0, 2), (-1, 2), 5),
                    ]
                )
            )
            story.append(tabela_assinaturas)

            # === RODAPÉ ===
            story.append(Spacer(1, 20))

            linha_rodape = Table([["", ""]], colWidths=[pdf_doc.width])
            linha_rodape.setStyle(
                TableStyle(
                    [
                        ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.grey),
                    ]
                )
            )
            story.append(linha_rodape)

            footer_style = ParagraphStyle(
                "Rodape",
                parent=styles["Normal"],
                fontSize=7,
                textColor=colors.HexColor("#666666"),
                alignment=1,
            )

            protocolo = metadata.get("protocolo", "N/A") if metadata else "N/A"
            footer_text = (
                "<b>Elite Sênior Consultoria Contábil</b> | "
                f"Documento gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} | "
                f"Este é um formulário para preenchimento manual - Protocolo: {protocolo}"
            )
            story.append(Spacer(1, 5))
            story.append(Paragraph(footer_text, footer_style))

            # Construir PDF
            pdf_doc.build(story)

            # Calcular hash SHA-256 do arquivo gerado
            import hashlib

            hasher = hashlib.sha256()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    hasher.update(chunk)
            doc_hash = hasher.hexdigest()

            # Adicionar hash ao final do documento usando PyPDF2
            # PdfReader/PdfWriter foram importados no nível do módulo (ver início do arquivo)
            from reportlab.pdfgen import canvas as pdf_canvas
            from io import BytesIO

            # Ler o PDF gerado
            reader = PdfReader(filepath)
            writer = PdfWriter()

            # Copiar todas as páginas
            for page in reader.pages:
                writer.add_page(page)

            # Criar uma nova página com o hash
            packet = BytesIO()
            can = pdf_canvas.Canvas(packet, pagesize=A4)
            can.setFont("Helvetica-Bold", 10)
            can.drawCentredString(
                A4[0] / 2, A4[1] - 2 * cm, "AUTENTICIDADE DO DOCUMENTO"
            )
            can.setFont("Helvetica", 8)
            can.drawCentredString(A4[0] / 2, A4[1] - 2.5 * cm, "Hash SHA-256:")
            can.setFont("Courier", 7)
            # Dividir hash em duas linhas para caber
            can.drawCentredString(A4[0] / 2, A4[1] - 3 * cm, doc_hash[:64])
            can.drawCentredString(A4[0] / 2, A4[1] - 3.3 * cm, doc_hash[64:])
            can.setFont("Helvetica", 7)
            can.drawCentredString(
                A4[0] / 2,
                A4[1] - 3.8 * cm,
                f"Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}",
            )
            can.save()
            packet.seek(0)

            # Adicionar a nova página
            hash_page = PdfReader(packet)
            writer.add_page(hash_page.pages[0])

            # Salvar o PDF atualizado
            with open(filepath, "wb") as f:
                writer.write(f)

            logger.info(
                f"✅ PDF profissional gerado: {safe_name} | Hash: {doc_hash[:16]}..."
            )
            return True

        except Exception as e:
            logger.error(f"❌ Erro ao gerar PDF {filename}: {e}", exc_info=True)
            return False

    def _calcular_valores_documento(
        self, doc_type: str, dados: Dict, metadata: Dict
    ) -> Optional[Dict]:
        """
        Calcula valores reais do documento ANTES de gerar PDF

        Args:
            doc_type: Tipo de documento (rescisao, folha_pagamento, etc)
            dados: Dados extraídos da mensagem
            metadata: Metadados adicionais

        Returns:
            Dict com itens calculados e total_liquido, ou None se não conseguir calcular
        """
        try:
            # Extrair dados do contexto da sessão se disponível
            session_context = metadata.get("session_context", {})

            # Tentar extrair valores da mensagem ou contexto
            salario_base = (
                dados.get("salario")
                or session_context.get("salario")
                or metadata.get("salario")
            )

            if not salario_base:
                # Tentar extrair da pergunta do usuário
                pergunta = metadata.get("pergunta_usuario", "")
                match = re.search(
                    r"R?\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)", pergunta
                )
                if match:
                    valor_str = match.group(1).replace(".", "").replace(",", ".")
                    try:
                        salario_base = float(valor_str)
                    except ValueError:
                        pass

            if not salario_base:
                return None  # Não conseguiu extrair salário

            # Tipo de documento determina o cálculo
            if doc_type == "rescisao":
                # Calcular rescisão
                meses_trabalhados = (
                    dados.get("meses_trabalhados")
                    or session_context.get("meses_trabalhados")
                    or 12  # Default 1 ano
                )

                tipo_rescisao = (
                    dados.get("tipo_rescisao")
                    or session_context.get("tipo_rescisao")
                    or "pedido_demissao"  # Default
                )

                # Determine dias trabalhados no mês (compatível com ferramentas que
                # aceitam 'dias_mes' ou 'dias_trabalhados_mes'). Preferência: valores
                # explícitos em `dados` ou no contexto da sessão; fallback para 15.
                dias_mes = (
                    dados.get("dias_mes")
                    or dados.get("dias_trabalhados_mes")
                    or session_context.get("dias_mes")
                    or session_context.get("dias_trabalhados_mes")
                    or 15
                )

                try:
                    dias_mes = int(dias_mes)
                except Exception:
                    dias_mes = 15

                # Send both legacy and explicit day-based keys to maximize compatibility
                payload = {
                    "salario": salario_base,
                    "meses_trabalbados": int(meses_trabalhados),
                    "tipo_rescisao": tipo_rescisao,
                    "dependentes_irr": 0,
                    "dias_mes": dias_mes,
                    "dias_trabalhados_mes": dias_mes,
                }

                resultado = self.calculadora.calcular_rescisao(payload)

                # Montar itens para exibição
                itens = []
                if resultado.get("saldo_salario", 0) > 0:
                    itens.append(
                        {
                            "descricao": "Saldo de Salário",
                            "valor": resultado["saldo_salario"],
                            "obs": "Proporcional",
                        }
                    )
                if resultado.get("decimo_terceiro", 0) > 0:
                    itens.append(
                        {
                            "descricao": "13º Salário Proporcional",
                            "valor": resultado["decimo_terceiro"],
                            "obs": "",
                        }
                    )
                if resultado.get("ferias_proporcionais", 0) > 0:
                    itens.append(
                        {
                            "descricao": "Férias Proporcionais",
                            "valor": resultado["ferias_proporcionais"],
                            "obs": "",
                        }
                    )
                if resultado.get("um_terco_ferias", 0) > 0:
                    itens.append(
                        {
                            "descricao": "1/3 de Férias",
                            "valor": resultado["um_terco_ferias"],
                            "obs": "Constitucional",
                        }
                    )
                if resultado.get("aviso_previo", 0) > 0:
                    itens.append(
                        {
                            "descricao": "Aviso Prévio Indenizado",
                            "valor": resultado["aviso_previo"],
                            "obs": "",
                        }
                    )
                if resultado.get("multa_fgts_40", 0) > 0:
                    itens.append(
                        {
                            "descricao": "Multa FGTS 40%",
                            "valor": resultado["multa_fgts_40"],
                            "obs": "Sobre FGTS",
                        }
                    )

                # Descontos
                if resultado.get("desconto_inss", 0) > 0:
                    itens.append(
                        {
                            "descricao": "(-) Desconto INSS",
                            "valor": -resultado["desconto_inss"],
                            "obs": "Previdência",
                        }
                    )
                if resultado.get("desconto_irr", 0) > 0:
                    itens.append(
                        {
                            "descricao": "(-) Desconto IRRF",
                            "valor": -resultado["desconto_irr"],
                            "obs": "Imposto de Renda",
                        }
                    )

                return {
                    "itens": itens,
                    "total_liquido": resultado.get("total_liquido", 0),
                }

            elif doc_type == "folha_pagamento":
                # Calcular folha de pagamento
                # Verificar adicionais
                periculosidade = session_context.get("periculosidade", 0) or dados.get(
                    "periculosidade", 0
                )
                horas_extras = session_context.get("horas_extras", 0) or dados.get(
                    "horas_extras", 0
                )

                salario_base_dec = Decimal(str(salario_base))

                # Proventos
                itens = [
                    {
                        "descricao": "Salário Base",
                        "valor": float(salario_base_dec),
                        "obs": "Mensal",
                    }
                ]

                total_proventos = salario_base_dec

                if periculosidade:
                    valor_peric = (
                        salario_base_dec * Decimal(str(periculosidade)) / Decimal("100")
                    )
                    itens.append(
                        {
                            "descricao": f"Periculosidade ({periculosidade}%)",
                            "valor": float(valor_peric),
                            "obs": "Adicional",
                        }
                    )
                    total_proventos += valor_peric

                if horas_extras:
                    # Assume hora extra 50%
                    valor_hora = salario_base_dec / Decimal("220")  # ~mês de 220h
                    valor_he = valor_hora * Decimal("1.5") * Decimal(str(horas_extras))
                    itens.append(
                        {
                            "descricao": f"Horas Extras ({horas_extras}h @ 50%)",
                            "valor": float(valor_he),
                            "obs": "",
                        }
                    )
                    total_proventos += valor_he

                # Descontos
                inss = self.calculadora.calcular_inss(total_proventos)
                irrf_result = self.calculadora.calcular_irrf(
                    total_proventos, 0, details=True
                )
                irrf = irrf_result.get("irr", Decimal("0"))

                itens.append(
                    {
                        "descricao": "(-) INSS",
                        "valor": -float(inss),
                        "obs": "Previdência",
                    }
                )

                if irrf > 0:
                    itens.append(
                        {
                            "descricao": "(-) IRRF",
                            "valor": -float(irrf),
                            "obs": "Imposto de Renda",
                        }
                    )

                total_liquido = total_proventos - inss - irrf

                return {"itens": itens, "total_liquido": float(total_liquido)}

            return None  # Tipo de documento não suportado para cálculo automático

        except Exception as e:
            logger.warning(f"Erro ao calcular valores: {e}")
            return None

    def detect_document_type(self, message: str) -> str:
        """Detecta tipo de documento baseado na mensagem do usuário"""
        msg_lower = message.lower()

        # Transferência - prioridade alta
        if (
            "transfer" in msg_lower
            or "transferi" in msg_lower
            or "trnsferiodo" in msg_lower
            or (
                "posto" in msg_lower
                and ("para" in msg_lower or "pra" in msg_lower or "agora" in msg_lower)
            )
            or "aditivo" in msg_lower
        ):
            return "transferencia"
        elif "rescis" in msg_lower or "demis" in msg_lower:
            return "rescisao"
        elif "ferias" in msg_lower or "férias" in msg_lower:
            return "ferias"
        elif "13" in msg_lower or "decimo" in msg_lower:
            return "decimo_terceiro"
        elif "folha" in msg_lower or "pagamento" in msg_lower:
            return "folha_pagamento"
        elif "imposto" in msg_lower or "irp" in msg_lower or "irr" in msg_lower:
            return "impostos"
        elif "inss" in msg_lower or "previdencia" in msg_lower:
            return "inss"
        elif "fgts" in msg_lower:
            return "fgts"
        else:
            return "consulta"


# Singleton global
document_service = DocumentService()

# Backwards-compatible module-level wrappers in case callers import the
# module object instead of the instance. These forward to the singleton
# `document_service` instance so legacy code can call e.g.:
#     from services import document_service
#     document_service.detect_document_type(msg)
# without needing to access the `document_service` attribute on the module.


def detect_document_type(message: str) -> str:
    return document_service.detect_document_type(message)


def should_generate_pdf(message: str, resposta: str | None = None) -> bool:
    return document_service.should_generate_pdf(message, resposta)


def generate_professional_pdf(nome_arquivo: str, conteudo: str, metadata: dict) -> bool:
    return document_service.generate_professional_pdf(nome_arquivo, conteudo, metadata)


def sanitize_filename(name: str) -> str:
    return document_service.sanitize_filename(name)


# Expose output_folder for compatibility
output_folder = document_service.output_folder


# ----------------- Simple Background Worker (in-process) -----------------
_task_queue = Queue()
_task_status = {}


def _worker_loop():
    while True:
        job = _task_queue.get()
        if job is None:
            break
        job_id = job.get("job_id")
        filename = job.get("filename")
        content = job.get("content")
        metadata = job.get("metadata")
        _task_status[job_id] = {
            "status": "running",
            "filename": filename,
            "started_at": time.time(),
        }
        try:
            ok = document_service.generate_professional_pdf(filename, content, metadata)
            _task_status[job_id]["status"] = "done" if ok else "failed"
            _task_status[job_id]["ok"] = bool(ok)
            _task_status[job_id]["finished_at"] = time.time()
        except Exception as e:
            _task_status[job_id]["status"] = "failed"
            _task_status[job_id]["error"] = str(e)
            _task_status[job_id]["finished_at"] = time.time()
        finally:
            _task_queue.task_done()


_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
_worker_thread.start()


def enqueue_generate(filename: str, content: str, metadata: dict) -> str:
    """Enfileira geração de PDF e retorna job_id."""
    job_id = str(uuid.uuid4())
    _task_status[job_id] = {
        "status": "queued",
        "filename": filename,
        "queued_at": time.time(),
    }
    _task_queue.put(
        {
            "job_id": job_id,
            "filename": filename,
            "content": content,
            "metadata": metadata,
        }
    )
    return job_id


def get_task_status(job_id: str) -> dict | None:
    return _task_status.get(job_id)


# Backwards-compatible exports
__all__ = [
    "document_service",
    "detect_document_type",
    "should_generate_pdf",
    "generate_professional_pdf",
    "sanitize_filename",
    "output_folder",
    "enqueue_generate",
    "get_task_status",
]
