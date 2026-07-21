import io
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename
from contabil_agente.services.pdf_store import register_pdf, get_metadata


# --- IMPORTS DO MÃ“DULO INTELLIGENCE ---
# Adicionar raiz do projeto ao path para encontrar 'intelligence'
_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Importar componentes de inteligÃªncia
INTELLIGENCE_AVAILABLE = False
IntelligenceOrchestrator = None
TaxEngine = None
ComplianceChecker = None
ForensicAudit = None

try:
    from intelligence.orchestrator import IntelligenceOrchestrator
    from intelligence.calculator import TaxEngine
    from intelligence.compliance import ComplianceChecker
    from intelligence.audit import ForensicAudit

    INTELLIGENCE_AVAILABLE = True
except ImportError as e:
    logging.warning(f"âš ï¸ MÃ³dulos intelligence nÃ£o disponÃ­veis: {e}")

# InstÃ¢ncias singleton dos componentes
_orchestrator = None
_tax_engine = None
_compliance = None
_audit = None


def get_intelligence_orchestrator():
    """ObtÃ©m instÃ¢ncia do IntelligenceOrchestrator (lazy init)"""
    global _orchestrator
    if _orchestrator is None and INTELLIGENCE_AVAILABLE:
        try:
            _orchestrator = IntelligenceOrchestrator()
            logging.info("âœ… IntelligenceOrchestrator inicializado")
        except Exception as e:
            logging.warning(f"âš ï¸ Falha ao inicializar orchestrator: {e}")
    return _orchestrator


def get_tax_engine():
    """ObtÃ©m instÃ¢ncia do TaxEngine (lazy init)"""
    global _tax_engine
    if _tax_engine is None and INTELLIGENCE_AVAILABLE:
        try:
            _tax_engine = TaxEngine()
            logging.info("âœ… TaxEngine inicializado")
        except Exception as e:
            logging.warning(f"âš ï¸ Falha ao inicializar TaxEngine: {e}")
    return _tax_engine


def get_compliance_checker():
    """ObtÃ©m instÃ¢ncia do ComplianceChecker (lazy init)"""
    global _compliance
    if _compliance is None and INTELLIGENCE_AVAILABLE:
        try:
            _compliance = ComplianceChecker()
            logging.info("âœ… ComplianceChecker inicializado")
        except Exception as e:
            logging.warning(f"âš ï¸ Falha ao inicializar ComplianceChecker: {e}")
    return _compliance


def get_forensic_audit():
    """ObtÃ©m instÃ¢ncia do ForensicAudit (lazy init)"""
    global _audit
    if _audit is None and INTELLIGENCE_AVAILABLE:
        try:
            _audit = ForensicAudit()
            logging.info("âœ… ForensicAudit inicializado")
        except Exception as e:
            logging.warning(f"âš ï¸ Falha ao inicializar ForensicAudit: {e}")
    return _audit


# --- IMPORTS LAZY LOADING (Python 3.14 fix) ---
def _import_groq():
    """Importa Groq de forma segura para Python 3.14"""
    global Groq
    try:
        from groq import Groq

        return True
    except Exception as e:
        logging.error(f"Erro ao importar Groq: {e}")
        return False


def _import_reportlab():
    """Importa reportlab de forma segura para Python 3.14"""
    global A4, getSampleStyleSheet, ParagraphStyle, Paragraph, SimpleDocTemplate
    global Spacer, Table, TableStyle, colors, cm
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

        return True
    except Exception as e:
        logging.error(f"Erro ao importar reportlab: {e}")
        return False


# --- IMPORTAÃ‡ÃƒO DO GERADOR DE PDF DE TRANSFERÃŠNCIA ---
try:
    from utils.pdf_transfer_generator import generate_transfer_addendum_pdf

    PDF_TRANSFER_AVAILABLE = True
except ImportError:
    PDF_TRANSFER_AVAILABLE = False

    def generate_transfer_addendum_pdf(payload, metadata=None):
        return {
            "success": False,
            "error": "Gerador de PDF de transferência não disponível",
        }


# --- IMPORTAÇÃO DO MÓDULO DE TIPOS DE DOCUMENTO ---
try:
    from routes.tipos_documento import (
        TIPOS_DOCUMENTO,
        detectar_tipo_documento,
        extrair_dados_documento,
        verificar_dados_completos,
        gerar_mensagem_coleta,
    )

    TIPOS_DOC_AVAILABLE = True
except ImportError:
    TIPOS_DOC_AVAILABLE = False
    TIPOS_DOCUMENTO = {}

    def detectar_tipo_documento(t):
        return "consulta"

    def extrair_dados_documento(t, txt):
        return {}

    def verificar_dados_completos(t, d):
        return True, []

    def gerar_mensagem_coleta(t, f):
        return ""


# --- INTEGRAÇÃO COM AGENTE CONTÁBIL ---
# Importa o orquestrador principal que coordena cálculos, PDFs e auditoria
AGENTE_CONTABIL_AVAILABLE = False
AgenteContabil = None
_agente_contabil_instance = None

try:
    # Tentar import quando rodando de fora do pacote
    from contabil_agente.agent_contabil import (
        AgenteContabil,
        calcular_ferias,
        calcular_13_salario,
    )

    AGENTE_CONTABIL_AVAILABLE = True
    logging.info("✅ AgenteContabil integrado com sucesso")
except ImportError:
    try:
        # Tentar import quando rodando de dentro do pacote contabil_agente
        from agent_contabil import (
            AgenteContabil,
            calcular_ferias,
            calcular_13_salario,
        )

        AGENTE_CONTABIL_AVAILABLE = True
        logging.info("✅ AgenteContabil integrado com sucesso (path interno)")
    except ImportError as e:
        logging.warning(f"⚠️ AgenteContabil não disponível: {e}")


def get_agente_contabil():
    """Obtém instância do AgenteContabil (lazy loading)"""
    global _agente_contabil_instance
    if _agente_contabil_instance is None and AGENTE_CONTABIL_AVAILABLE:
        try:
            _agente_contabil_instance = AgenteContabil()
            logging.info("✅ Instância do AgenteContabil criada")
        except Exception as e:
            logging.warning(f"⚠️ Falha ao criar AgenteContabil: {e}")
    return _agente_contabil_instance


def processar_via_agente(tipo_documento: str, dados: dict, meta: dict = None) -> dict:
    """
    Processa um documento usando o AgenteContabil.

    Args:
        tipo_documento: Tipo do documento (rescisao, ferias, decimo_terceiro, etc)
        dados: Dicionário com os dados coletados
        meta: Metadados adicionais (session_id, etc)

    Returns:
        dict com resultado do processamento (success, pdf_path, resultado, etc)
    """
    agente = get_agente_contabil()

    if agente is None:
        logging.warning("AgenteContabil não disponível, usando fallback")
        return {
            "success": False,
            "error": "AgenteContabil não disponível",
            "fallback": True,
        }

    try:
        # Mapear tipo de documento para dados esperados pelo agente
        dados_processamento = {"tipo_documento": tipo_documento, **dados}

        # Usar o fluxo completo do agente: calcular -> gerar_pdf -> assinar
        resultado = agente.processar_pedido(dados_processamento, meta=meta or {})

        if resultado.get("success"):
            logging.info(
                f"✅ Documento {tipo_documento} processado pelo AgenteContabil"
            )
            return {
                "success": True,
                "resultado": resultado.get("resultado"),
                "pdf_path": resultado.get("pdf_info", {}).get("path"),
                "assinatura": resultado.get("assinatura"),
            }
        else:
            return {
                "success": False,
                "error": resultado.get("error", "Erro desconhecido"),
            }

    except Exception as e:
        logging.error(f"Erro ao processar via AgenteContabil: {e}")
        return {"success": False, "error": str(e)}


# --- CONFIGURAÇÃO AVANÇADA ---
chat_blueprint = Blueprint("chat", __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_FOLDER = os.path.join(BASE_DIR, "temp_docs")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AgenteContabilElite")
# Aviso de deprecaÃ§Ã£o: este mÃ³dulo Ã© o legacy monolÃ­tico.
# Use `routes/chat_refactored.py` ou `routes/chat_multi_tenant.py`.
# Registrar como DEBUG para nÃ£o poluir logs de INFO/PROD
logger.debug(
    "[DEPRECATION] routes/chat.py estÃ¡ obsoleto. Use routes/chat_refactored.py ou routes/chat_multi_tenant.py"
)

# Lazy loading do client Groq para evitar erro de inicializaÃ§Ã£o
_groq_client = None


def get_groq_client():
    """Retorna instÃ¢ncia do client Groq (lazy loading)"""
    global _groq_client
    if _groq_client is None:
        # Importar Groq de forma lazy (Python 3.14 fix)
        if not _import_groq():
            logging.error("Falha ao importar Groq")
            return None
        api_key = os.getenv("GROQ_API_KEY")
        # Masked logging for key presence (never log full secret)
        try:
            masked = (
                api_key[:4] + "..." + api_key[-4:]
                if api_key and len(api_key) > 8
                else ("<set>" if api_key else "<not set>")
            )
        except Exception:
            masked = "<not set>"
        logging.info(
            f"get_groq_client: GROQ_API_KEY present: {bool(api_key)} (masked={masked})"
        )

        # Basic format validation to avoid calling provider with clearly-bad keys
        try:
            import re

            if api_key and not re.match(r"^gsk_[A-Za-z0-9_-]{10,}$", api_key):
                logging.error(
                    "GROQ_API_KEY format appears invalid; ignoring to avoid auth errors"
                )
                api_key = None
        except Exception:
            # If regex import fails, do not block flow — best-effort only
            pass

        # Fallback 1: tentar ler do arquivo .env do pacote (se existir)
        if not api_key:
            try:
                from dotenv import load_dotenv

                env_file = os.path.join(os.path.dirname(__file__), ".env")
                if os.path.exists(env_file):
                    load_dotenv(dotenv_path=env_file)
                    api_key = os.getenv("GROQ_API_KEY")
            except Exception:
                # python-dotenv pode nÃ£o estar instalado; ignorar
                pass

        # Fallback 2 (Windows): tentar ler variÃ¡vel do registro do usuÃ¡rio
        if not api_key and os.name == "nt":
            try:
                import winreg

                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as rk:
                        val, _ = winreg.QueryValueEx(rk, "GROQ_API_KEY")
                        if val:
                            api_key = val
                except Exception:
                    api_key = None
            except Exception:
                # winreg indisponÃ­vel em alguns ambientes (nÃ£o-Windows)
                api_key = None

        if api_key:
            try:
                _groq_client = Groq(api_key=api_key)
            except Exception as e:
                logging.error(f"Falha ao inicializar Groq client: {e}")
                logging.info(
                    "get_groq_client: attempted to init Groq client but failed"
                )
                _groq_client = None
        else:
            logging.error("GROQ_API_KEY nÃ£o encontrada")
            logging.info(
                "get_groq_client: attempted fallbacks (dotenv/registry) and no key found"
            )
    return _groq_client


# MemÃ³ria inteligente com contexto expandido
historico_conversas: Dict[str, Dict[str, Any]] = {}
rate_limit_ip_store: Dict[str, Dict[str, Any]] = {}

# Conhecimento especializado em memÃ³ria
CONHECIMENTO_ESPECIALIZADO = {
    "clt": {
        "rescisao": (
            "Art. 477-491 CLT - CÃ¡lculos: aviso prÃ©vio, 13Âº proporcional, "
            "fÃ©rias vencidas + 1/3, multa 40% FGTS"
        ),
        "ferias": (
            "Art. 130-145 CLT - PerÃ­odo aquisitivo 12 meses, concessÃ£o "
            "12 meses subsequentes, 1/3 constitucional"
        ),
        "salario": (
            "Art. 76-86 CLT - ComposiÃ§Ã£o: bÃ¡sico + adicionais "
            "(periculosidade 30%, insalubridade 10-40%) + horas extras 50-100%"
        ),
        "fgts": (
            "Lei 8.036/90 - DepÃ³sito mensal 8%, multa rescisÃ³ria 40%, "
            "saque em demissÃ£o sem justa causa"
        ),
    },
    "fiscal": {
        "simples_nacional": (
            "Anexos I-VI, faixas 4-33%, inclui tributos federais, "
            "estaduais e municipais"
        ),
        "lucro_presumido": (
            "PresunÃ§Ã£o: serviÃ§os 32%, comÃ©rcio 8%, IRPJ 15% + 10%, CSLL 9-20%"
        ),
        "mei": ("Limite R$ 81k/ano, DAS mensal R$ 70,60, contabilidade simplificada"),
    },
    "juridico": {
        "riscos": (
            "Processos trabalhistas mÃ©dia R$ 30k por aÃ§Ã£o, autuaÃ§Ãµes "
            "fiscais 75-150% multa + juros"
        ),
        "compliance": (
            "LGPD Lei 13.709, eSocial obrigatÃ³rio, SPED fiscal e contÃ¡bil"
        ),
    },
}


# ImplementaÃ§Ãµes locais movidas para fallback (fim do arquivo)


def _extrair_contexto_negocio_local(mensagem: str) -> Dict[str, Any]:
    """Extrai automaticamente contexto de negÃ³cio da mensagem (implementaÃ§Ã£o local)"""
    contexto = {
        "tipo_empresa": None,
        "regime_tributario": None,
        "funcionarios": None,
        "faturamento": None,
        "localidade": None,
    }

    # DetecÃ§Ã£o de regime tributÃ¡rio
    if re.search(
        r"simples\s*nacional|anexo\s+[iI]+[iI]*|simples", mensagem, re.IGNORECASE
    ):
        contexto["regime_tributario"] = "simples_nacional"
    elif re.search(r"presumido|lucro\s+presumido", mensagem, re.IGNORECASE):
        contexto["regime_tributario"] = "lucro_presumido"
    elif re.search(r"real|lucro\s+real", mensagem, re.IGNORECASE):
        contexto["regime_tributario"] = "lucro_real"

    # DetecÃ§Ã£o de nÃºmero de funcionÃ¡rios
    match = re.search(
        r"(\d+)\s*(funcion[Ã¡a]rio|colaborador|empregado)", mensagem, re.IGNORECASE
    )
    if match:
        contexto["funcionarios"] = int(match.group(1))

    # DetecÃ§Ã£o de faturamento
    match = re.search(
        r"faturamento\s*(de\s*)?R?\$?\s*(\d+[.,]?\d*)", mensagem, re.IGNORECASE
    )
    if match:
        contexto["faturamento"] = float(
            match.group(2).replace(".", "").replace(",", ".")
        )

    # DetecÃ§Ã£o de localidade
    match = re.search(
        r"(sp|sÃ£o paulo|rj|rio|mg|minas|pr|paranÃ¡|rs|rio grande)",
        mensagem,
        re.IGNORECASE,
    )
    if match:
        contexto["localidade"] = match.group(1).upper()

    return contexto


# Alias para uso padrÃ£o (serÃ¡ sobrescrito se serviÃ§o centralizado estiver disponÃ­vel)
extrair_contexto_negocio = _extrair_contexto_negocio_local


def sanitize_filename(filename: str) -> Optional[str]:
    """SanitizaÃ§Ã£o segura de nomes de arquivo"""
    try:
        # retirar qualquer componente de caminho
        filename = os.path.basename(filename)
        # decodificar percent-encoding (ex: nomes vindos de URLs)
        try:
            from urllib.parse import unquote_plus

            filename = unquote_plus(filename)
        except Exception:
            pass
        # normalizar unicode (compatibilidade e remoÃ§Ã£o de composiÃ§Ãµes)
        try:
            import unicodedata

            filename = unicodedata.normalize("NFKC", filename)
        except Exception:
            pass

        # Construir nome seguro: permitir letras (inclui acentos), digitos e um pequeno conjunto de sinais seguros
        safe_chars = set(" _-.()")
        out = []
        for ch in filename:
            # permitir letras de qualquer alfabeto e digitos
            cat = None
            try:
                import unicodedata as _ud

                cat = _ud.category(ch)
            except Exception:
                cat = None
            if cat and cat.startswith("L"):
                out.append(ch)
            elif cat and cat.startswith("N"):
                out.append(ch)
            elif ch in safe_chars:
                out.append(ch)
            # ignorar outros caracteres potencialmente perigosos

        # substituir espaÃ§os por underline e garantir nÃ£o vazio
        safe = "".join(out).strip()
        if not safe:
            return None
        safe = safe.replace(" ", "_")
        # evitar nomes com navegacao de caminho
        if "/" in safe or "\\" in safe:
            return None
        return safe
    except Exception:
        return None


def deve_gerar_pdf_automaticamente(mensagem_usuario: str, resposta_ia: str) -> bool:
    """Detecta automaticamente se deve gerar PDF baseado no contexto"""

    msg_lower = mensagem_usuario.lower()
    resp_lower = resposta_ia.lower()

    # âŒ PERGUNTAS SIMPLES NÃƒO GERAM PDF
    # Se a mensagem Ã© uma pergunta simples (comeÃ§a com "quanto", "qual", "como", etc.)
    # e nÃ£o menciona explicitamente documento/PDF, nÃ£o gerar
    eh_pergunta_simples = bool(
        re.search(r"^\s*(quanto|qual|como|o que|quem|onde|quando)\s", msg_lower)
    )

    # Se menciona explicitamente "documento" ou "pdf", nÃ£o Ã© pergunta simples
    pede_documento_explicitamente = bool(
        re.search(r"\b(documento|pdf|gerar|gere|emitir|emita)\b", msg_lower)
    )

    # Pergunta simples sem pedido explÃ­cito de documento = nÃ£o gerar PDF
    if eh_pergunta_simples and not pede_documento_explicitamente:
        return False

    # âœ… PALAVRAS-CHAVE QUE INDICAM NECESSIDADE DE DOCUMENTO
    keywords_docs = [
        "rescis",
        "demis",
        "folha",
        "documento",
        "relatÃ³rio",
        "relatorio",
        "comprovante",
        "atestado",
        "termo",
    ]

    # âœ… FRASES QUE PEDEM DOCUMENTOS
    keywords_pedido = [
        "gera",
        "cria",
        "emite",
        "manda",
        "envia",
        "pd",
        "formul",
    ]

    # Verificar se hÃ¡ palavras-chave de documentos
    tem_doc_keyword = any(kw in msg_lower or kw in resp_lower for kw in keywords_docs)

    # Verificar se hÃ¡ pedido explÃ­cito
    tem_pedido = any(kw in msg_lower for kw in keywords_pedido)

    # Verificar se resposta tem cÃ¡lculos (valores R$)
    tem_calculos = bool(re.search(r"R?\$\s*[\d.,]+", resposta_ia))

    # Verificar se Ã© uma resposta longa (mais de 300 chars = resposta detalhada)
    resposta_detalhada = len(resposta_ia) > 300

    # âœ… GERAR PDF se:
    # 1. Tem keyword de documento E tem pedido explÃ­cito
    # 2. OU tem pedido E resposta detalhada com cÃ¡lculos
    deve_gerar = (tem_doc_keyword and tem_pedido) or (
        tem_pedido and resposta_detalhada and tem_calculos
    )

    if deve_gerar:
        logger.info(
            f"âœ… PDF serÃ¡ gerado | Doc: {tem_doc_keyword} | Pedido: {tem_pedido} | CÃ¡lculos: {tem_calculos}"
        )

    return deve_gerar


def check_security_limits(ip: str, text: str) -> bool:
    """Controle avanÃ§ado de rate limiting"""
    # Allow local/internal IPs unrestricted to support internal probes and bulk tests
    try:
        if (
            ip in ("127.0.0.1", "::1")
            or ip.startswith("192.168.")
            or ip.startswith("10.")
            or ip.startswith("172.")
        ):
            return True
    except Exception:
        pass
    if len(text) > 10000:
        logger.warning(f"Texto muito longo de {ip}: {len(text)} chars")
        return False

    now = time.time()

    if ip not in rate_limit_ip_store:
        rate_limit_ip_store[ip] = {
            "requests": [],
            "blocked_until": 0,
            "daily_requests": 0,
            "last_reset": now,
        }

    # Reset diÃ¡rio
    if now - rate_limit_ip_store[ip]["last_reset"] > 86400:
        rate_limit_ip_store[ip]["daily_requests"] = 0
        rate_limit_ip_store[ip]["last_reset"] = now

    # Verificar bloqueio
    if now < rate_limit_ip_store[ip]["blocked_until"]:
        logger.warning(f"IP bloqueado: {ip}")
        return False

    # Limite por minuto
    rate_limit_ip_store[ip]["requests"] = [
        t for t in rate_limit_ip_store[ip]["requests"] if now - t < 60
    ]

    if len(rate_limit_ip_store[ip]["requests"]) >= 20:
        rate_limit_ip_store[ip]["blocked_until"] = now + 600  # 10 minutos
        logger.warning(f"Rate limit excedido para {ip}")
        return False

    # Limite diÃ¡rio
    if rate_limit_ip_store[ip]["daily_requests"] >= 200:
        logger.warning(f"Limite diÃ¡rio excedido para {ip}")
        return False

    rate_limit_ip_store[ip]["requests"].append(now)
    rate_limit_ip_store[ip]["daily_requests"] += 1

    return True


def construir_pdf_profissional(
    nome_arquivo: str, conteudo: str, metadata: Dict = None
) -> bool:
    """Gera FORMULÃRIO PROFISSIONAL para preenchimento manual pelo cliente"""
    # Importar reportlab de forma segura (Python 3.14 fix)
    if not _import_reportlab():
        logging.error("Falha ao importar reportlab - PDF nÃ£o gerado")
        return False

    safe_name = sanitize_filename(nome_arquivo)
    if not safe_name:
        return False

    path = os.path.join(TEMP_FOLDER, safe_name)

    try:
        # Detectar tipo de documento para usar template apropriado
        tipo_doc = (
            metadata.get("tipo_documento", "consulta") if metadata else "consulta"
        )

        # ðŸŽ¨ CORES ÃšNICAS PARA CADA TIPO DE DOCUMENTO
        cores_por_tipo = {
            "rescisao": "#e74c3c",  # Vermelho (rescisÃ£o)
            "ferias": "#3498db",  # Azul (fÃ©rias)
            "decimo_terceiro": "#f39c12",  # Dourado (13Âº)
            "folha_pagamento": "#2ecc71",  # Verde (folha)
            "impostos": "#9b59b6",  # Roxo (impostos)
            "inss": "#1abc9c",  # Turquesa (INSS)
            "fgts": "#e67e22",  # Laranja (FGTS)
            "admissao": "#16a085",  # Verde escuro (admissÃ£o)
            "transferencia": "#8e44ad",  # Roxo escuro (transferência)
            "consulta": "#2dce89",  # Verde suave (consulta)
        }

        cor_documento = cores_por_tipo.get(tipo_doc, "#2dce89")

        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            rightMargin=60,
            leftMargin=60,
            topMargin=50,
            bottomMargin=50,
        )

        styles = getSampleStyleSheet()
        story = []

        # Estilos customizados ÃšNICOS para cada tipo de documento
        titulo_style = ParagraphStyle(
            "TituloFormulario",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            alignment=1,
            spaceAfter=8,
            textColor=colors.HexColor(cor_documento),  # ðŸŽ¨ COR ÃšNICA
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

        # === CABEÃ‡ALHO DO FORMULÃRIO ===
        # Determinar tÃ­tulo baseado no tipo de documento
        titulos_formulario = {
            "rescisao": "ðŸ“‹ RESCISÃƒO CONTRATUAL",
            "ferias": "ðŸ–ï¸ CÃLCULO DE FÃ‰RIAS",
            "decimo_terceiro": "ðŸ’° 13Âº SALÃRIO",
            "folha_pagamento": "ðŸ“Š FOLHA DE PAGAMENTO",
            "impostos": "ðŸ§¾ APURAÃ‡ÃƒO DE IMPOSTOS",
            "inss": "ðŸ¥ CONTRIBUIÃ‡ÃƒO INSS",
            "fgts": "ðŸ¦ FUNDO DE GARANTIA - FGTS",
            "admissao": "ðŸ‘¤ PROCESSO DE ADMISSÃƒO",
            "transferencia": "ðŸ”„ ADITIVO DE TRANSFERÃŠNCIA",
            "consulta": "ðŸ“„ ORIENTAÃ‡ÃƒO CONTÃBIL",
        }

        titulo_doc = titulos_formulario.get(tipo_doc, "ðŸ“„ DOCUMENTO CONTÃBIL")

        story.append(Paragraph(titulo_doc, titulo_style))
        story.append(Paragraph("Elite SÃªnior Consultoria ContÃ¡bil", subtitulo_style))

        # Linha divisÃ³ria com cor Ãºnica do documento
        linha_dados = [["", ""]]
        tabela_linha = Table(linha_dados, colWidths=[doc.width])
        tabela_linha.setStyle(
            TableStyle(
                [
                    (
                        "LINEABOVE",
                        (0, 0),
                        (-1, 0),
                        2.0,
                        colors.HexColor(cor_documento),
                    ),  # ðŸŽ¨ COR ÃšNICA
                ]
            )
        )
        story.append(tabela_linha)
        story.append(Spacer(1, 15))

        # === METADADOS ORGANIZADOS ===
        if metadata:
            meta_style = styles["Normal"]
            meta_style.fontSize = 10
            meta_style.leading = 14

            cliente = metadata.get("cliente", "Consulta Online")
            protocolo = metadata.get("protocolo", "N/A")
            data = datetime.now().strftime("%d/%m/%Y Ã s %H:%M")

            # Pergunta original do usuÃ¡rio (se disponÃ­vel)
            pergunta = metadata.get("pergunta_usuario", "")

            meta_html = f"""
            <b>INFORMAÃ‡Ã•ES DO DOCUMENTO</b><br/>
            <br/>
            <b>Cliente:</b> {cliente}<br/>
            <b>Data de EmissÃ£o:</b> {data}<br/>
            <b>Protocolo:</b> {protocolo}<br/>
            """

            if pergunta:
                # Limpar a pergunta de caracteres especiais
                pergunta_limpa = pergunta.replace("<", "&lt;").replace(">", "&gt;")
                meta_html += f"<b>Consulta Original:</b> {pergunta_limpa}<br/>"

            story.append(Paragraph(meta_html, meta_style))
            story.append(Spacer(1, 20))
            story.append(
                Paragraph("<hr width='100%' color='#cccccc'/>", styles["Normal"])
            )
            story.append(Spacer(1, 20))

        # === TÃTULO DA SEÃ‡ÃƒO ===
        section_title = styles["Heading3"]
        section_title.fontName = "Helvetica-Bold"
        section_title.fontSize = 12
        section_title.spaceAfter = 10
        section_title.textColor = "#2dce89"

        story.append(Paragraph("ANÃLISE TÃ‰CNICA E ORIENTAÃ‡Ã•ES", section_title))
        story.append(Spacer(1, 10))

        # === CONTEÃšDO PRINCIPAL COM FORMATAÃ‡ÃƒO PROFISSIONAL ===
        content_style = styles["BodyText"]
        content_style.fontName = "Helvetica"
        content_style.fontSize = 11
        content_style.leading = 16
        content_style.alignment = 4  # Justificado

        # Limpar marcadores de controle que nÃ£o devem aparecer no PDF
        conteudo_limpo = conteudo
        conteudo_limpo = re.sub(r"\[DOCUMENTO_OFICIAL\]", "", conteudo_limpo)
        conteudo_limpo = re.sub(r"\[SUMÃRIO_EXECUTIVO\]", "", conteudo_limpo)
        conteudo_limpo = re.sub(r"\[FIM_SUMÃRIO\]", "", conteudo_limpo)
        conteudo_limpo = re.sub(
            r"<pensamento>.*?</pensamento>", "", conteudo_limpo, flags=re.DOTALL
        )

        # Processar conteÃºdo mantendo formataÃ§Ã£o
        paragraphs = conteudo_limpo.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if para:
                # Detectar se Ã© um tÃ­tulo/seÃ§Ã£o (linha que termina com :)
                if para.endswith(":") and len(para) < 100:
                    section_style = styles["Heading4"]
                    section_style.fontName = "Helvetica-Bold"
                    section_style.fontSize = 11
                    section_style.spaceAfter = 6
                    section_style.spaceBefore = 12
                    story.append(Paragraph(para, section_style))
                else:
                    # Processar formataÃ§Ã£o markdown primeiro
                    formatted = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", para)
                    formatted = re.sub(r"\*(.*?)\*", r"<i>\1</i>", formatted)

                    # Detectar listas com bullet points
                    if para.startswith("â€¢"):
                        formatted = "&bull; " + formatted.lstrip("â€¢").lstrip()
                    elif para.startswith("-"):
                        formatted = "&bull; " + formatted.lstrip("-").lstrip()

                    # Substituir quebras de linha por <br/>
                    formatted = formatted.replace("\\n", "<br/>")

                    story.append(Paragraph(formatted, content_style))
                    story.append(Spacer(1, 8))

        # === EXTRAÃ‡ÃƒO DE DADOS DO CONTEÃšDO ===
        # Extrair informaÃ§Ãµes da resposta/contexto
        texto_completo = f"{conteudo_limpo} {metadata.get('pergunta_usuario', '')}"

        # Quando metadata indicar 'only_explicit', NÃƒO realizar extraÃ§Ã£o automÃ¡tica
        # a partir do texto: usar apenas campos explicitamente fornecidos pelo cliente
        # e manter placeholders para os demais campos.
        def extrair_valor(pattern, texto, default="Não informado"):
            match = re.search(pattern, texto, re.IGNORECASE)
            return match.group(1).strip() if match else default

        if metadata and metadata.get("only_explicit"):
            # Respeitar somente valores passados em metadata
            nome = metadata.get("nome", "A preencher")
            cpf = metadata.get("cp", "000.000.000-00")
            rg = metadata.get("rg", "00.000.000-0")
            cargo = metadata.get("cargo", "A definir")
            salario = metadata.get("salario", None)
        else:
            # Regex patterns para extraÃ§Ã£o
            # Extrair dados do colaborador
            nome = extrair_valor(
                r"(?:nome|funcionÃ¡rio|colaborador|empregado)[:|\s]+([A-ZÃÃ‰ÃÃ“ÃšÃ‡Ã€Ã‚ÃŠ][a-zÃ¡Ã©Ã­Ã³ÃºÃ§Ã Ã¢ÃªÃ´ÃµÃ£Ã¼\s]+(?:[A-ZÃÃ‰ÃÃ“ÃšÃ‡][a-zÃ¡Ã©Ã­Ã³ÃºÃ§Ã Ã¢ÃªÃ´ÃµÃ£Ã¼]+)*)",
                texto_completo,
                "A preencher",
            )
            cpf = extrair_valor(
                r"CPF[:|\s]+(\d{3}\.?\d{3}\.?\d{3}-?\d{2})",
                texto_completo,
                "000.000.000-00",
            )
            rg = extrair_valor(
                r"RG[:|\s]+(\d{1,2}\.?\d{3}\.?\d{3}-?[\dXx])",
                texto_completo,
                "00.000.000-0",
            )
            cargo = extrair_valor(
                r"(?:cargo|funÃ§Ã£o)[:|\s]+([A-Za-zA-Za-z\s]+(?=\.|,|$))",
                texto_completo,
                "A definir",
            )

            # Extrair valores monetÃ¡rios (salÃ¡rio, INSS, IRRF, etc)
            # Extrair salÃ¡rio somente se houver valor explÃ­cito no texto; caso contrÃ¡rio deixar como None
            salario = extrair_valor(
                r"(?:salÃ¡rio|remuneraÃ§Ã£o)[:|\s]*(?:de\s+)?R?\$?\s*([\d.,]+)",
                texto_completo,
                None,
            )

            # Se metadados foram fornecidos explicitamente, usÃ¡-los para preencher
            # os campos em preferÃªncia Ã  extraÃ§Ã£o automÃ¡tica (respeita pedido do cliente)
            if metadata:
                if metadata.get("nome"):
                    nome = metadata.get("nome")
                if metadata.get("cp"):
                    cpf = metadata.get("cp")
                if metadata.get("rg"):
                    rg = metadata.get("rg")
                if metadata.get("cargo"):
                    cargo = metadata.get("cargo")
                if metadata.get("salario"):
                    salario = metadata.get("salario")

        # Extrair valores de cÃ¡lculos (INSS, IRRF, lÃ­quido, etc.)
        calculos_encontrados = []

        # Se metadata indicar 'only_explicit' nÃ£o realizar extraÃ§Ã£o automÃ¡tica de
        # valores; mostrar apenas placeholder para valores a serem preenchidos.
        if metadata and metadata.get("only_explicit"):
            calculos_encontrados = [
                [
                    "(Valores serÃ£o preenchidos conforme cÃ¡lculo)",
                    "R$ _____________",
                    "Pendente",
                ]
            ]
        else:
            # PadrÃµes para cÃ¡lculos
            patterns_calculos = [
                (r"INSS[:|\s]*(?:de\s+)?R?\$?\s*([\d.,]+)", "INSS"),
                (r"IRRF[:|\s]*(?:de\s+)?R?\$?\s*([\d.,]+)", "IRRF"),
                (
                    r"(?:salÃ¡rio\s+)?lÃ­quido[:|\s]*R?\$?\s*([\d.,]+)",
                    "SalÃ¡rio LÃ­quido",
                ),
                (r"fÃ©rias[:|\s]*R?\$?\s*([\d.,]+)", "FÃ©rias"),
                (r"13Âº[:|\s]*(?:salÃ¡rio)?[:|\s]*R?\$?\s*([\d.,]+)", "13Âº SalÃ¡rio"),
                (r"FGTS[:|\s]*R?\$?\s*([\d.,]+)", "FGTS"),
                (r"rescisÃ£o[:|\s]*R?\$?\s*([\d.,]+)", "RescisÃ£o"),
            ]

            for pattern, desc in patterns_calculos:
                match = re.search(pattern, conteudo_limpo, re.IGNORECASE)
                if match:
                    valor = match.group(1)
                    calculos_encontrados.append([desc, f"R$ {valor}", "Calculado"])

            # Se nÃ£o encontrou cÃ¡lculos, adicionar linha com placeholders (nÃ£o preencher automaticamente)
            if not calculos_encontrados:
                calculos_encontrados = [
                    [
                        "(Valores serÃ£o preenchidos conforme cÃ¡lculo)",
                        "R$ _____________",
                        "Pendente",
                    ]
                ]

        # === DADOS DO COLABORADOR/BENEFICIÃRIO (PREENCHIDOS) ===
        story.append(Spacer(1, 20))
        story.append(Paragraph("<b>DADOS DO COLABORADOR/BENEFICIÃRIO</b>", label_style))
        story.append(Spacer(1, 10))

        # Mostrar placeholder para salÃ¡rio se nÃ£o foi informado explicitamente
        salario_display = (
            f"R$ {salario}"
            if salario and str(salario).strip() not in ("0", "0.00", "0,00")
            else "R$ _____________"
        )

        campos_dados = [
            ["Nome Completo:", nome],
            ["CPF:", cpf, "RG:", rg],
            [
                "Data de Nascimento:",
                "(Não informado)",
                "Data de AdmissÃ£o:",
                "(Não informado)",
            ],
            ["Cargo/FunÃ§Ã£o:", cargo],
            ["SalÃ¡rio Base:", salario_display, "CBO:", "(Consultar)"],
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
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#0066cc")),
                ]
            )
        )

        story.append(tabela_dados)
        story.append(Spacer(1, 20))

        # === SEÃ‡ÃƒO DE CÃLCULOS (VALORES REAIS EXTRAÃDOS) ===
        story.append(Paragraph("<b>CÃLCULOS E VALORES</b>", label_style))
        story.append(Spacer(1, 10))

        # CabeÃ§alho + linhas de cÃ¡lculos encontrados
        campos_calculos = [["DescriÃ§Ã£o", "Valor (R$)", "ObservaÃ§Ãµes"]]
        campos_calculos.extend(calculos_encontrados)

        # Calcular total se existirem valores
        total = 0.00
        found_numeric = False
        for calc in calculos_encontrados:
            # Tenta extrair valor numÃ©rico; se nÃ£o for possÃ­vel, ignora (mantÃ©m placeholder)
            valor_str = (
                calc[1].replace("R$", "").replace(".", "").replace(",", ".").strip()
            )
            try:
                val = float(valor_str)
                total += val
                found_numeric = True
            except (ValueError, TypeError):
                continue

        if found_numeric and total > 0:
            total_display = (
                f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
        else:
            total_display = "R$ _____________"

        campos_calculos.append(["TOTAL GERAL:", total_display, ""])

        tabela_calculos = Table(campos_calculos, colWidths=[7 * cm, 4 * cm, 5 * cm])
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
                        colors.HexColor(cor_documento),
                    ),  # ðŸŽ¨ COR ÃšNICA
                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (-1, 0),
                        colors.white,
                    ),  # Texto branco no cabeÃ§alho
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8f9fa")),
                    ("FONT", (0, -1), (0, -1), "Helvetica-Bold", 10),
                    (
                        "TEXTCOLOR",
                        (1, 1),
                        (1, -2),
                        colors.HexColor(cor_documento),
                    ),  # ðŸŽ¨ Valores na cor do doc
                ]
            )
        )

        story.append(tabela_calculos)
        story.append(Spacer(1, 20))

        # === OBSERVAÃ‡Ã•ES IMPORTANTES (EXTRAÃDAS) ===
        story.append(Paragraph("<b>OBSERVAÃ‡Ã•ES IMPORTANTES</b>", label_style))
        story.append(Spacer(1, 8))

        # Extrair pontos importantes da resposta
        obs_texto = (
            "Este documento foi gerado automaticamente com base na consulta realizada. "
        )
        obs_texto += "Valores e informaÃ§Ãµes foram extraÃ­dos do contexto fornecido. "
        obs_texto += "Verifique todos os dados antes de utilizar oficialmente."

        obs_style = ParagraphStyle(
            "Observacoes",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#555555"),
            leading=14,
        )
        story.append(Paragraph(obs_texto, obs_style))
        story.append(Spacer(1, 8))

        # === ASSINATURAS ===
        story.append(Spacer(1, 25))

        assinaturas_data = [
            ["", "", ""],
            ["_" * 35, "_" * 35, "_" * 35],
            [
                "ResponsÃ¡vel pelo Preenchimento",
                "Contador(a) ResponsÃ¡vel",
                "AutorizaÃ§Ã£o/Visto",
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

        # === RODAPÃ‰ DO FORMULÃRIO ===
        story.append(Spacer(1, 20))

        linha_rodape = Table([["", ""]], colWidths=[doc.width])
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

        # Garantir que 'protocolo' exista mesmo que metadata seja None
        protocolo = metadata.get("protocolo", "N/A") if metadata else "N/A"

        footer_text = (
            "<b>Elite SÃªnior Consultoria ContÃ¡bil</b> | "
            f"Documento gerado automaticamente em {datetime.now().strftime('%d/%m/%Y Ã s %H:%M')} | "
            f"<b>Protocolo Ãºnico:</b> {protocolo} | <i>Dados extraÃ­dos da consulta realizada</i>"
        )
        story.append(Spacer(1, 5))
        story.append(Paragraph(footer_text, footer_style))

        # Construir PDF
        doc.build(story)
        # Log detalhado com caminho absoluto para facilitar diagnÃ³stico de disponibilidade
        logger.info(f"âœ… PDF profissional gerado: {safe_name} (path={path})")
        return True

    except Exception as e:
        logger.error(f"âŒ Erro na geraÃ§Ã£o de PDF: {e}", exc_info=True)
        return False


def limpar_conversas_antigas():
    """Limpa conversas com mais de 2 horas de inatividade"""
    while True:
        time.sleep(3600)  # Executar a cada hora
        now = time.time()
        to_remove = []

        for session_id, data in historico_conversas.items():
            if now - data.get("last_activity", 0) > 7200:  # 2 horas
                to_remove.append(session_id)

        for session_id in to_remove:
            del historico_conversas[session_id]

        if to_remove:
            logger.info(
                f"Limpeza automÃ¡tica: removidas {len(to_remove)} conversas antigas"
            )


# Iniciar thread de limpeza
cleanup_thread = threading.Thread(target=limpar_conversas_antigas, daemon=True)
cleanup_thread.start()


@chat_blueprint.route("/download/<filename>")
def obter_documento(filename):
    """Endpoint para download seguro de documentos"""
    safe_name = sanitize_filename(filename)
    if not safe_name:
        return jsonify({"erro": "Nome de arquivo invÃ¡lido"}), 400

    filepath = os.path.join(TEMP_FOLDER, safe_name)
    # Debug: log which folder and filepath we're checking to diagnose 404 when file exists elsewhere
    logger.info(
        "legacy_download_request: filename=%s temp_folder=%s filepath=%s",
        safe_name,
        TEMP_FOLDER,
        filepath,
    )
    if not os.path.exists(filepath):
        # Fornecer diagnÃ³stico mÃ­nimo sem expor nomes de arquivos individuais
        try:
            available = len(
                [f for f in os.listdir(TEMP_FOLDER) if f.lower().endswith(".pd")]
            )
        except Exception:
            available = 0
        # Fallback: verificar `document_service.output_folder` como outra possÃ­vel localizaÃ§Ã£o
        try:
            from contabil_agente.services import document_service as _ds_mod

            _ds = (
                getattr(_ds_mod, "document_service", None)
                or getattr(_ds_mod, "DocumentService", None)
                or _ds_mod
            )
            if hasattr(_ds, "get_instance"):
                try:
                    _ds = _ds.get_instance()
                except Exception:
                    pass
            out_folder = getattr(_ds, "output_folder", None)
            if out_folder:
                alt_path = os.path.join(out_folder, safe_name)
                if os.path.exists(alt_path):
                    logger.info(
                        f"legacy_download_fallback_found: {alt_path} (serving from document_service.output_folder)"
                    )
                    return send_from_directory(
                        out_folder, safe_name, as_attachment=True
                    )
        except Exception:
            pass
        # Additional backward-compatible check: look in contabil_agente/static/downloads
        try:
            base = os.path.dirname(os.path.dirname(__file__))
            static_downloads = os.path.join(base, "static", "downloads")
            static_path = os.path.join(static_downloads, safe_name)
            if os.path.exists(static_path):
                logger.info(
                    "legacy_download_found_in_static: serving %s from %s",
                    safe_name,
                    static_downloads,
                )
                return send_from_directory(
                    static_downloads, safe_name, as_attachment=True
                )
        except Exception:
            pass
        logger.warning(
            "legacy_download_not_found: checked_path=%s available_pdfs=%s",
            filepath,
            available,
        )
        return (
            jsonify(
                {
                    "erro": "Arquivo nÃ£o encontrado",
                    "requested": safe_name,
                    "available_pdfs": available,
                }
            ),
            404,
        )

    # Verificar se o arquivo é recente (menos de 24 horas)
    try:
        file_age = time.time() - os.path.getmtime(filepath)
    except Exception:
        file_age = 0

    # Always persist PDFs to static/downloads when being downloaded to provide
    # stable URLs and long-term availability for clients. This moves the file
    # from TEMP_FOLDER -> static/downloads and registers metadata.
    try:
        base = os.path.dirname(os.path.dirname(__file__))
        static_downloads = os.path.join(base, "static", "downloads")
        # register_pdf will move the file and create manifest entry
        try:
            dest_name = register_pdf(filepath, session_id=None)
        except Exception as e:
            # If register fails, fall back to serving from temp (if still allowed by age)
            logger.warning(f"pdf_store.register_pdf failed for {filepath}: {e}")
            # If file is too old, still return 410 to avoid serving stale temp files
            if file_age > 86400:
                try:
                    available = len(
                        [
                            f
                            for f in os.listdir(TEMP_FOLDER)
                            if f.lower().endswith(".pdf")
                        ]
                    )
                except Exception:
                    available = 0
                logger.info(
                    f"Arquivo expirado solicitado: {safe_name} (age_seconds={int(file_age)})"
                )
                return (
                    jsonify(
                        {
                            "erro": "Arquivo expirado",
                            "requested": safe_name,
                            "available_pdfs": available,
                        }
                    ),
                    410,
                )
            return send_from_directory(TEMP_FOLDER, safe_name, as_attachment=True)

        # Audit: record the download action
        try:
            logs_dir = os.path.join(base, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            audit_log = os.path.join(logs_dir, "download_audit.log")
            with open(audit_log, "a", encoding="utf-8") as af:
                af.write(
                    f"{datetime.utcnow().isoformat()}Z\t{request.remote_addr}\t{dest_name}\n"
                )
        except Exception:
            pass

        return send_from_directory(static_downloads, dest_name, as_attachment=True)
    except Exception:
        # fallback: if anything unexpected happens, try serving from temp or return 404
        try:
            return send_from_directory(TEMP_FOLDER, safe_name, as_attachment=True)
        except Exception:
            return (
                jsonify({"erro": "Arquivo não encontrado", "requested": safe_name}),
                404,
            )


@chat_blueprint.route("/download/latest")
def obter_documento_latest():
    """Endpoint para baixar o PDF mais recente gerado no servidor."""
    try:
        files = [f for f in os.listdir(TEMP_FOLDER) if f.lower().endswith(".pdf")]
        if not files:
            return jsonify({"erro": "Nenhum PDF disponÃ­vel"}), 404

        files.sort(
            key=lambda fn: os.path.getmtime(os.path.join(TEMP_FOLDER, fn)), reverse=True
        )
        latest = files[0]

        # SeguranÃ§a: garantir nome seguro
        safe_name = sanitize_filename(latest)
        if not safe_name:
            # fallback: enviar com nome original sem sanitizaÃ§Ã£o (apenas se existir)
            safe_name = latest

        return send_from_directory(TEMP_FOLDER, safe_name, as_attachment=True)
    except Exception as e:
        logger.error(f"Erro ao obter Ãºltimo documento: {e}", exc_info=True)
        return jsonify({"erro": "Falha ao obter arquivo", "detalhes": str(e)}), 500


@chat_blueprint.route("/api/chat", methods=["POST"])
def processar_chat():
    """Endpoint principal do agente contÃ¡bil inteligente"""
    # DEBUG: registrar via logger em vez de escrever em caminho absoluto
    try:
        logger.info("=== processar_chat() iniciado ===")
    except Exception:
        pass
    ip = request.remote_addr or "127.0.0.1"

    try:
        dados = request.get_json(force=True)
        if not dados:
            return jsonify({"erro": "Dados JSON invÃ¡lidos"}), 400

        # Permitir confirmaÃ§Ã£o separada: aceitar {'confirmado': true} sem 'mensagem'
        confirmado = bool(dados.get("confirmado", False))
        msg_bruta = (dados.get("mensagem", "") or "").strip()
        if not msg_bruta and not confirmado:
            return jsonify({"erro": "Mensagem vazia"}), 400

        uid = dados.get("session_id")

        # Gerar novo ID se nÃ£o existir
        if not uid or not re.match(r"^[a-f0-9\-]{36}$", uid):
            uid = str(uuid.uuid4())

        # Verificar limites de seguranÃ§a
        if not check_security_limits(ip, msg_bruta):
            return (
                jsonify(
                    {
                        "resposta": "Limite de solicitaÃ§Ãµes excedido. Por favor, aguarde alguns minutos antes de nova consulta.",
                        "status": "rate_limit",
                    }
                ),
                429,
            )

        # NormalizaÃ§Ã£o avanÃ§ada
        msg_limpa = normalizar_texto_avancado(msg_bruta)

        # Extrair contexto de negÃ³cio
        contexto_negocio = extrair_contexto_negocio(msg_limpa)

        # NÃƒO detectar perfil automaticamente - ser neutra e perguntar quando necessÃ¡rio
        perfil_detectado = "neutro"  # Sempre neutro, adapta conforme conversa

        # Inicializar ou recuperar sessÃ£o
        if uid not in historico_conversas:
            historico_conversas[uid] = {
                "messages": [],
                "contexto": contexto_negocio,
                "perfil": perfil_detectado,
                "created_at": time.time(),
                "last_activity": time.time(),
            }

        # ðŸ”¥ SEMPRE recria o system prompt (para pegar as atualizaÃ§Ãµes mais recentes)
        # Remove o system prompt antigo se existir
        historico_conversas[uid]["messages"] = [
            msg
            for msg in historico_conversas[uid]["messages"]
            if msg.get("role") != "system"
        ]

        # SEM detecÃ§Ã£o automÃ¡tica de perfil - seja neutra e inteligente
        try:
            from core.prompts import get_system_prompt

            system_prompt = get_system_prompt()
        except Exception:
            # Fallback: try to import the canonical prompt constant, else use a minimal placeholder
            try:
                from core.prompts import SYSTEM_PROMPT

                system_prompt = SYSTEM_PROMPT
            except Exception:
                system_prompt = "Maria Helena - assistente contÃ¡bil. Seja cordial e pergunte pelo contexto do cliente."

        # Adiciona o system prompt atualizado no inÃ­cio do histÃ³rico
        historico_conversas[uid]["messages"].insert(
            0, {"role": "system", "content": system_prompt}
        )

        # Atualizar perfil detectado se mudou
        historico_conversas[uid]["perfil"] = perfil_detectado

        # Atualizar contexto se novo for mais rico
        if contexto_negocio["regime_tributario"]:
            historico_conversas[uid]["contexto"].update(contexto_negocio)

        # Atualizar atividade
        historico_conversas[uid]["last_activity"] = time.time()

        # ===== VERIFICAR CONFIRMAÃ‡ÃƒO PENDENTE PRIMEIRO =====
        # Se hÃ¡ uma solicitaÃ§Ã£o pendente de PDF e usuÃ¡rio confirmou, gerar imediatamente
        pending = historico_conversas[uid].get("pending_generation")
        simple_confirm = bool(
            re.match(
                r"^\s*(sim|s|confirmo|confirmar|ok|yes)\s*[!.]*$",
                msg_limpa,
                re.IGNORECASE,
            )
        )
        confirmado_flag = bool(dados.get("confirmado", False))

        if pending and (confirmado_flag or simple_confirm):
            # Usar dados armazenados na pendÃªncia
            arquivo_id = pending.get("arquivo_id")
            conteudo_pdf = pending.get("conteudo_pdf") or pending.get(
                "conteudo_pd"
            )  # compatibilidade
            metadata = pending.get("metadata", {})
            tipo_doc = metadata.get("tipo_documento", "documento")

            # Remover pendÃªncia
            historico_conversas[uid].pop("pending_generation", None)

            # Gerar PDF
            try:
                from contabil_agente.services.document_service import (
                    enqueue_generate,
                    get_task_status,
                )

                job_id = enqueue_generate(arquivo_id, conteudo_pdf, metadata)
                gerou = False
                for _ in range(10):
                    st = get_task_status(job_id)
                    if st and st.get("status") == "done" and st.get("ok"):
                        gerou = True
                        break
                    if st and st.get("status") == "failed":
                        break
                    time.sleep(0.5)
            except Exception:
                gerou = construir_pdf_profissional(arquivo_id, conteudo_pdf, metadata)

            if gerou:
                download_path = f"/download/{arquivo_id}"
                pdf_url = download_path
                download_link = request.host_url.rstrip("/") + download_path
                logger.info(f"âœ… PDF gerado (confirmado): {arquivo_id}")
                resposta_final = f"Pronto! Gerei o documento de {tipo_doc}. VocÃª pode baixar aqui: {download_link}"
                historico_conversas[uid]["messages"].append(
                    {"role": "assistant", "content": resposta_final}
                )
                return jsonify(
                    {
                        "session_id": uid,
                        "resposta": resposta_final,
                        "pensamento": "",
                        "pdf_url": pdf_url,
                        "download_link": download_link,
                        "perfil_detectado": historico_conversas[uid]["perfil"],
                        "contexto": historico_conversas[uid]["contexto"],
                        "status": "sucesso",
                        "timestamp": datetime.now().isoformat(),
                        "intelligence_status": {
                            "available": INTELLIGENCE_AVAILABLE,
                            "orchestrator": get_intelligence_orchestrator() is not None,
                            "tax_engine": get_tax_engine() is not None,
                            "compliance": get_compliance_checker() is not None,
                            "audit": get_forensic_audit() is not None,
                        },
                    }
                )
            else:
                logger.warning("âŒ Falha ao gerar PDF apÃ³s confirmaÃ§Ã£o")
                resposta_erro = "Desculpe, houve um problema ao gerar o documento. Posso tentar novamente se vocÃª quiser."
                historico_conversas[uid]["messages"].append(
                    {"role": "assistant", "content": resposta_erro}
                )
                return jsonify(
                    {
                        "session_id": uid,
                        "resposta": resposta_erro,
                        "status": "erro",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        # Adicionar mensagem do usuÃ¡rio ao histÃ³rico (formato natural para memÃ³ria)
        # Contexto do negÃ³cio Ã© adicionado apenas se relevante
        if any(v for v in historico_conversas[uid]["contexto"].values() if v):
            primeiro_turno = (
                len(
                    [
                        m
                        for m in historico_conversas[uid]["messages"]
                        if m.get("role") == "user"
                    ]
                )
                == 0
            )
            if primeiro_turno:
                # Primeira mensagem: incluir contexto detectado
                historico_conversas[uid]["messages"].append(
                    {
                        "role": "user",
                        "content": f"[Contexto: {json.dumps(historico_conversas[uid]['contexto'], ensure_ascii=False)}]\n{msg_limpa}",
                    }
                )
            else:
                # Mensagens seguintes: apenas o conteÃºdo natural
                historico_conversas[uid]["messages"].append(
                    {"role": "user", "content": msg_limpa}
                )
        else:
            historico_conversas[uid]["messages"].append(
                {"role": "user", "content": msg_limpa}
            )

        # VerificaÃ§Ã£o rÃ¡pida: se o usuÃ¡rio pediu explicitamente para GERAR/ENVIAR um documento,
        # podemos gerar o PDF imediatamente a partir do contexto da conversa sem aguardar a resposta do modelo.
        try:
            # Checar se Ã© pergunta simples (nÃ£o deve gerar PDF)
            eh_pergunta_simples = bool(
                re.search(
                    r"^\s*(quanto|qual|como|o que|quem|onde|quando)\s",
                    msg_limpa,
                    re.IGNORECASE,
                )
            )

            # Detecção mais ampla: reconhecer diversas formas em que o usuário pede
            # para gerar/enviar/emitir um documento ou PDF, incluindo variações comuns.
            # Nota: Removido \b final pois prefixos como "rescis" não terminam em word boundary
            trigger_direct_generate = bool(
                re.search(
                    r"\b(gerar|gere|gere\s+um|emitir|emita|enviar|anexar|anexo|fazer|faça|preciso|quero)\b.*(documento|pdf|termo|rescis|aditivo|transfer|ferias|férias|13|decimo|folha|fgts|inss|holerite|imposto)",
                    msg_limpa,
                    re.IGNORECASE,
                )
            ) or bool(
                re.search(
                    r"(documento|pdf|rescis|rescisão|termo|aditivo|transfer|ferias|férias|decimo|13|folha|fgts|inss|holerite|imposto)",
                    msg_limpa,
                    re.IGNORECASE,
                )
                and bool(
                    re.search(
                        r"\b(preciso|quero|por favor|gere|gera|crie|fazer|faça)\b",
                        msg_limpa,
                        re.IGNORECASE,
                    )
                )
            )

            # Se Ã© pergunta simples, nÃ£o gerar PDF automaticamente
            if eh_pergunta_simples:
                trigger_direct_generate = False

            # Se o cliente incluir a flag 'force_quick_path', forÃ§ar o trigger
            force_quick_flag = bool(dados.get("force_quick_path", False))
            if force_quick_flag:
                trigger_direct_generate = True
        except Exception:
            trigger_direct_generate = False

        # DEBUG: registrar trigger via logger
        try:
            logger.info(
                "trigger_direct_generate = %s para mensagem: %s",
                trigger_direct_generate,
                msg_limpa[:100],
            )
        except Exception:
            pass

        # Verificar se estamos aguardando dados de QUALQUER tipo de documento do contexto anterior
        contexto_atual = historico_conversas[uid].get("contexto", {})
        aguardando = False
        for key in contexto_atual:
            if key.startswith("aguardando_dados_") and contexto_atual.get(key):
                aguardando = True
                break
        try:
            logger.debug(
                "uid=%s, contexto=%s, aguardando=%s", uid, contexto_atual, aguardando
            )
        except Exception:
            pass
        if aguardando:
            # Forçar processamento para coletar dados
            trigger_direct_generate = True
            try:
                logger.info(">>> Contexto aguardando_dados=True, forçando trigger")
            except Exception:
                pass

        if trigger_direct_generate:
            # Montar conteÃºdo do PDF a partir da requisiÃ§Ã£o do usuÃ¡rio.
            # Preencher apenas campos explicitamente mencionados na mensagem;
            # deixar placeholders para os demais para respeitar a ordem do cliente.
            try:
                # HeurÃ­stica para identificar tipo de documento
                msg_lower = msg_limpa.lower()
                tipo_doc = "consulta"
                if "rescis" in msg_lower or "demis" in msg_lower:
                    tipo_doc = "rescisao"
                elif "ferias" in msg_lower or "férias" in msg_lower:
                    tipo_doc = "ferias"
                elif "13" in msg_lower or "decimo" in msg_lower:
                    tipo_doc = "decimo_terceiro"
                elif "folha" in msg_lower or "pagamento" in msg_lower:
                    tipo_doc = "folha_pagamento"
                elif "imposto" in msg_lower or "irp" in msg_lower or "irr" in msg_lower:
                    tipo_doc = "impostos"
                elif "inss" in msg_lower or "previdencia" in msg_lower:
                    tipo_doc = "inss"
                elif "fgts" in msg_lower:
                    tipo_doc = "fgts"
                elif (
                    "transfer" in msg_lower
                    or "aditivo" in msg_lower
                    or "trocar de posto" in msg_lower
                    or "mudar de posto" in msg_lower
                ):
                    tipo_doc = "transferencia"
                    logger.info(f"ðŸ” TIPO_DOC detectado: transferencia")

                # Se o contexto indica aguardando dados de QUALQUER tipo, forçar tipo_doc
                for ctx_key in contexto_atual:
                    if ctx_key.startswith("aguardando_dados_") and contexto_atual.get(
                        ctx_key
                    ):
                        tipo_doc = ctx_key.replace("aguardando_dados_", "")
                        try:
                            logger.info(
                                ">>> Forçando tipo_doc=%s por contexto interno",
                                tipo_doc,
                            )
                        except Exception:
                            pass
                        break

                # === NOVA LÓGICA: Processar TODOS os tipos de documento com módulo centralizado ===
                if (
                    TIPOS_DOC_AVAILABLE
                    and tipo_doc in TIPOS_DOCUMENTO
                    and tipo_doc != "transferencia"
                ):
                    # Buscar dados no histórico da conversa (APENAS mensagens do usuário)
                    historico_texto_user = " ".join(
                        [
                            m.get("content", "")
                            for m in historico_conversas.get(uid, {}).get(
                                "messages", []
                            )
                            if m.get("role") == "user"
                        ]
                    )
                    texto_completo = historico_texto_user + " " + msg_bruta

                    # Extrair dados usando módulo centralizado
                    dados_extraidos = extrair_dados_documento(tipo_doc, texto_completo)

                    # Verificar se temos dados suficientes
                    dados_completos, campos_faltando = verificar_dados_completos(
                        tipo_doc, dados_extraidos
                    )

                    # DEBUG: registrar checks via logger
                    try:
                        logger.debug("=== %s CHECK ===", tipo_doc.upper())
                        logger.debug("dados_extraidos=%s", dados_extraidos)
                        logger.debug(
                            "dados_completos=%s, faltando=%s",
                            dados_completos,
                            campos_faltando,
                        )
                    except Exception:
                        pass

                    if not dados_completos:
                        # Pedir dados faltantes
                        mensagem_coleta = gerar_mensagem_coleta(
                            tipo_doc, campos_faltando
                        )

                        historico_conversas[uid]["messages"].append(
                            {"role": "assistant", "content": mensagem_coleta}
                        )
                        historico_conversas[uid]["contexto"][
                            f"aguardando_dados_{tipo_doc}"
                        ] = True
                        historico_conversas[uid]["contexto"][
                            "dados_parciais"
                        ] = dados_extraidos

                        return jsonify(
                            {
                                "session_id": uid,
                                "resposta": mensagem_coleta,
                                "pensamento": f"Coletando dados para {TIPOS_DOCUMENTO[tipo_doc]['nome_display']}",
                                "status": "aguardando_dados",
                                "timestamp": datetime.now().isoformat(),
                            }
                        )

                    # Dados completos! Gerar documento
                    # Limpar contexto de coleta
                    historico_conversas[uid]["contexto"].pop(
                        f"aguardando_dados_{tipo_doc}", None
                    )
                    historico_conversas[uid]["contexto"].pop("dados_parciais", None)

                    # === INTEGRAÇÃO COM AGENTE CONTÁBIL ===
                    # Primeiro tentar usar o AgenteContabil para processamento completo
                    config_tipo = TIPOS_DOCUMENTO[tipo_doc]

                    if AGENTE_CONTABIL_AVAILABLE:
                        try:
                            resultado_agente = processar_via_agente(
                                tipo_documento=tipo_doc,
                                dados=dados_extraidos,
                                meta={
                                    "session_id": uid,
                                    "protocolo": uid,
                                    "data_consulta": datetime.now().strftime(
                                        "%d/%m/%Y %H:%M"
                                    ),
                                },
                            )

                            if resultado_agente.get("success"):
                                pdf_path = resultado_agente.get("pdf_path")
                                if pdf_path and os.path.exists(pdf_path):
                                    arquivo_id = os.path.basename(pdf_path)
                                    download_path = f"/download/{arquivo_id}"
                                    download_link = (
                                        request.host_url.rstrip("/") + download_path
                                    )
                                    logger.info(
                                        f"✅ PDF de {tipo_doc} gerado via AgenteContabil: {arquivo_id}"
                                    )

                                    resposta_final = f"Pronto! Gerei o documento de {config_tipo['nome_display']}. Você pode baixar aqui: {download_link}"
                                    historico_conversas[uid]["messages"].append(
                                        {"role": "assistant", "content": resposta_final}
                                    )

                                    return jsonify(
                                        {
                                            "session_id": uid,
                                            "resposta": resposta_final,
                                            "pensamento": f"{config_tipo['nome_display']} processado pelo AgenteContabil!",
                                            "pdf_url": download_path,
                                            "filename": arquivo_id,
                                            "download_link": download_link,
                                            "status": "sucesso",
                                            "assinatura": resultado_agente.get(
                                                "assinatura"
                                            ),
                                            "timestamp": datetime.now().isoformat(),
                                        }
                                    )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Fallback para PDF local após erro do agente: {e}"
                            )

                    # === FALLBACK: Gerar PDF localmente ===
                    labels = config_tipo.get("labels", {})

                    conteudo_lines = ["[DOCUMENTO_OFICIAL]"]
                    conteudo_lines.append(f"{config_tipo['nome_display'].upper()}:")
                    conteudo_lines.append("")

                    # Adicionar todos os dados extraídos
                    for campo, valor in dados_extraidos.items():
                        label = labels.get(campo, campo.replace("_", " ").title())
                        conteudo_lines.append(f"{label}: {valor}")

                    conteudo_pdf = "\n".join(conteudo_lines)

                    arquivo_id = f"{tipo_doc}_{uid[:8]}_{int(time.time())}.pdf"
                    metadata = {
                        "cliente": "Consulta Online",
                        "protocolo": uid,
                        "data_consulta": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "tipo_documento": tipo_doc,
                        "dados": dados_extraidos,
                    }

                    # Tentar gerar PDF
                    try:
                        gerou = construir_pdf_profissional(
                            arquivo_id, conteudo_pdf, metadata
                        )
                        if gerou:
                            download_path = f"/download/{arquivo_id}"
                            download_link = request.host_url.rstrip("/") + download_path
                            logger.info(f"✅ PDF de {tipo_doc} gerado: {arquivo_id}")

                            resposta_final = f"Pronto! Gerei o documento de {config_tipo['nome_display']}. Você pode baixar aqui: {download_link}"
                            historico_conversas[uid]["messages"].append(
                                {"role": "assistant", "content": resposta_final}
                            )

                            return jsonify(
                                {
                                    "session_id": uid,
                                    "resposta": resposta_final,
                                    "pensamento": f"{config_tipo['nome_display']} gerado com sucesso!",
                                    "pdf_url": download_path,
                                    "filename": arquivo_id,
                                    "download_link": download_link,
                                    "status": "sucesso",
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )
                    except Exception as e:
                        logger.error(
                            f"Erro ao gerar PDF de {tipo_doc}: {e}", exc_info=True
                        )
                # === FIM DA NOVA LÓGICA ===

                # FunÃ§Ãµes locais de extraÃ§Ã£o (apenas valores explÃ­citos)
                def extrair_simples_nome(texto):
                    # Padrao 0: "nome é X" ou "o nome é X"
                    m = re.search(
                        r"(?:o\s+)?nome\s+(?:[eé]\s+)?([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*?)(?:\s*,|\s+CPF|\s+cpf|\s+ele|\s+ela|\s+do\s+|\s+está|\s*$)",
                        texto,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(1).strip()
                    # Padrao 1: nome: X ou nome X
                    m = re.search(
                        r"nome[:\s]+([A-Z][A-Za-zÀ-ÿ\s,.-]{2,})",
                        texto,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(1).strip()
                    # Padrao 2: para o funcionario X ou funcionario X
                    m = re.search(
                        r"(?:para\s+o\s+)?funcion.rio\s+([A-Z][A-Za-zÀ-ÿ\s]{2,}?)(?:\s*,|\s+CPF|\s+cpf|\s+do\s+posto|\s+que|\s+$)",
                        texto,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(1).strip()
                    # Padrao 3: Nome antes de CPF (e.g., Maria Silva CPF 123...)
                    m = re.search(
                        r"(?:para|transferir)\s+([A-Z][A-Za-zÀ-ÿ\s]{2,}?)\s+CPF",
                        texto,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(1).strip()
                    # Padrao 4: "é pro/pra/para X" informal (e.g., é pro João Carlos)
                    m = re.search(
                        r"(?:[eé]\s+)?(?:pro|pra|para)\s+([A-Za-z\u00C0-\u017F]+(?:\s+[A-Za-z\u00C0-\u017F]+)*)",
                        texto,
                        re.IGNORECASE,
                    )
                    if m:
                        # Verificar se não é um lugar (posto, filial, etc)
                        nome = m.group(1).strip()
                        if not re.search(
                            r"^(posto|filial|local|norte|sul|leste|oeste|centro)$",
                            nome,
                            re.IGNORECASE,
                        ):
                            return nome
                    return None

                def extrair_cpf(texto):
                    m = re.search(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b", texto)
                    return m.group(1) if m else None

                def extrair_salario(texto):
                    m = re.search(r"R?\$\s*([\d\.\,]+)", texto)
                    return m.group(1) if m else None

                def extrair_aviso_indenizado(texto):
                    return bool(
                        re.search(r"aviso\s+pr[iÃ­]vio\s+indeniz", texto, re.IGNORECASE)
                    )

                # Use raw user message for extraction to preserve case/format like 'R$'
                nome_ex = extrair_simples_nome(msg_bruta)
                cpf_ex = extrair_cpf(msg_bruta)
                salario_ex = extrair_salario(msg_bruta)
                aviso_ind = extrair_aviso_indenizado(msg_bruta)

                # Montar conteÃºdo do documento de rescisÃ£o (respeitando apenas campos informados)
                conteudo_lines = []
                if tipo_doc == "rescisao":
                    conteudo_lines.append("[DOCUMENTO_OFICIAL]")
                    conteudo_lines.append("SUMÃRIO EXECUTIVO:")
                    conteudo_lines.append(
                        "Documento de rescisÃ£o solicitado pelo cliente. Campos preenchidos apenas quando explicitados na mensagem."
                    )
                    conteudo_lines.append("")
                    conteudo_lines.append("DADOS DO COLABORADOR:")
                    conteudo_lines.append(
                        f"Nome: {nome_ex if nome_ex else '___________________________'}"
                    )
                    conteudo_lines.append(
                        f"CPF: {cpf_ex if cpf_ex else '____.___.___-__'}"
                    )
                    conteudo_lines.append(f"Cargo/FunÃ§Ã£o: {'(Não informado)'}")
                    conteudo_lines.append(
                        f"SalÃ¡rio Base: {('R$ ' + salario_ex) if salario_ex else 'R$ _____________'}"
                    )
                    conteudo_lines.append("")
                    conteudo_lines.append("TIPO DE RESCISÃƒO:")
                    conteudo_lines.append(
                        "Aviso PrÃ©vio Indenizado: Sim"
                        if aviso_ind
                        else "Aviso PrÃ©vio Indenizado: A confirmar"
                    )
                    conteudo_lines.append("")
                    conteudo_lines.append("CÃLCULOS E VALORES:")
                    # Se salÃ¡rio foi informado, apresentar o campo; nÃ£o efetuar cÃ¡lculos automÃ¡ticos
                    if salario_ex:
                        conteudo_lines.append(f"SalÃ¡rio informado: R$ {salario_ex}")
                        conteudo_lines.append(
                            "Outros valores (INSS, IRRF, FGTS, 13Âº, FÃ©rias): a serem calculados conforme legislaÃ§Ã£o e verificaÃ§Ãµes"
                        )
                    else:
                        conteudo_lines.append("SalÃ¡rio: R$ _____________")
                        conteudo_lines.append(
                            "(Nenhum cÃ¡lculo automÃ¡tico realizado â€” forneÃ§a valores para cÃ¡lculo)"
                        )

                    conteudo_lines.append("")
                    conteudo_lines.append("OBSERVAÃ‡Ã•ES:")
                    conteudo_lines.append(
                        "Este documento foi gerado a partir da solicitaÃ§Ã£o do usuÃ¡rio. Verifique e confirme todos os dados antes de uso oficial."
                    )

                elif tipo_doc == "transferencia":
                    # TRANSFERÊNCIA: Usar gerador especializado de PDF de aditivo
                    # Extrair dados específicos para transferência
                    def extrair_local_destino(texto):
                        # Padrões para capturar novo local/posto
                        patterns = [
                            r"(?:vai\s+(?:pro|para\s+o?|para))\s+(?:posto|filial|unidade|local)?\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
                            r"(?:pro|para\s+o?)\s+(?:posto|filial|unidade|local)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
                            r"(?:novo\s+(?:posto|local|filial))[:\s]+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
                        ]
                        for pattern in patterns:
                            m = re.search(pattern, texto, re.IGNORECASE)
                            if m:
                                return m.group(1).strip()
                        return None

                    def extrair_local_origem(texto):
                        patterns = [
                            r"(?:do\s+(?:posto|local|filial))\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
                            r"(?:está\s+no\s+(?:posto|local)?)\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
                            r"(?:atual(?:mente)?|atualmente?\s+(?:no|em))\s+(?:posto|local)?\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
                        ]
                        for pattern in patterns:
                            m = re.search(pattern, texto, re.IGNORECASE)
                            if m:
                                return m.group(1).strip()
                        return None

                    def extrair_data_transferencia(texto):
                        m = re.search(r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})", texto)
                        return m.group(1) if m else None

                    # Buscar dados no histórico da conversa (APENAS mensagens do usuário)
                    historico_texto = " ".join(
                        [
                            m.get("content", "")
                            for m in historico_conversas.get(uid, {}).get(
                                "messages", []
                            )
                            if m.get("role")
                            == "user"  # IMPORTANTE: ignorar respostas da IA
                        ]
                    )

                    nome_transfer = extrair_simples_nome(
                        historico_texto
                    ) or extrair_simples_nome(msg_bruta)
                    cpf_transfer = extrair_cpf(historico_texto) or extrair_cpf(
                        msg_bruta
                    )
                    local_origem = extrair_local_origem(historico_texto)
                    local_destino = extrair_local_destino(historico_texto)
                    data_transfer = extrair_data_transferencia(
                        historico_texto
                    ) or datetime.now().strftime("%d/%m/%Y")

                    # Se temos dados suficientes, gerar PDF de transferência
                    # Precisa ter: (nome ou CPF) E (origem ou destino)
                    tem_identificacao = bool(nome_transfer) or bool(cpf_transfer)
                    tem_locais = bool(local_origem) or bool(local_destino)
                    dados_suficientes = tem_identificacao and tem_locais

                    # DEBUG: registrar via logger em vez de arquivo local
                    try:
                        logger.debug("=== TRANSFER CHECK ===")
                        logger.debug("nome=%r, cpf=%r", nome_transfer, cpf_transfer)
                        logger.debug(
                            "origem=%r, destino=%r", local_origem, local_destino
                        )
                        logger.debug(
                            "tem_id=%s, tem_locais=%s, dados_ok=%s",
                            tem_identificacao,
                            tem_locais,
                            dados_suficientes,
                        )
                    except Exception:
                        pass

                    logger.info(
                        f"TRANSFER DEBUG: PDF={PDF_TRANSFER_AVAILABLE}, nome={nome_transfer}, cpf={cpf_transfer}, "
                        f"origem={local_origem}, destino={local_destino}, dados_ok={dados_suficientes}"
                    )

                    # Se não tem dados suficientes, pedir ao usuário
                    if not dados_suficientes:
                        dados_faltando = []
                        if not nome_transfer:
                            dados_faltando.append("nome do funcionário")
                        if not cpf_transfer:
                            dados_faltando.append("CPF")
                        if not local_origem:
                            dados_faltando.append("posto atual")
                        if not local_destino:
                            dados_faltando.append("novo posto")

                        resposta_pedir = (
                            "Certo! Para gerar o aditivo de transferência, preciso de mais alguns dados:\n- "
                            + "\n- ".join(dados_faltando)
                            + "\n\nPode me informar?"
                        )

                        historico_conversas[uid]["messages"].append(
                            {"role": "assistant", "content": resposta_pedir}
                        )
                        historico_conversas[uid]["contexto"][
                            "aguardando_dados_transferencia"
                        ] = True

                        return jsonify(
                            {
                                "session_id": uid,
                                "resposta": resposta_pedir,
                                "pensamento": "Coletando dados para aditivo de transferência",
                                "status": "aguardando_dados",
                                "timestamp": datetime.now().isoformat(),
                            }
                        )

                    if PDF_TRANSFER_AVAILABLE and dados_suficientes:
                        payload_transfer = {
                            "nome": nome_transfer or "Funcionário",
                            "cpf": cpf_transfer or "Não informado",
                            "local_origem": local_origem or "Local Atual",
                            "local_destino": local_destino or "Novo Local",
                            "data_transferencia": data_transfer,
                            "cargo": "Funcionário",
                            "empresa": "Empresa Contratante",
                        }

                        pdf_result = generate_transfer_addendum_pdf(
                            payload=payload_transfer,
                            metadata={
                                "author": "Maria Helena - Sistema ContÃ¡bil",
                                "title": "Aditivo de TransferÃªncia",
                            },
                        )

                        if pdf_result.get("success"):
                            pdf_path = pdf_result.get("pdf_path")
                            filename = pdf_result.get("filename")
                            download_path = f"/download/{filename}"
                            download_link = request.host_url.rstrip("/") + download_path

                            logger.info(f"âœ… PDF de transferência gerado: {pdf_path}")

                            resposta_transferencia = f"Pronto! Gerei o aditivo de transferência. VocÃª pode baixar aqui: {download_link}"
                            historico_conversas[uid]["messages"].append(
                                {"role": "assistant", "content": resposta_transferencia}
                            )

                            return jsonify(
                                {
                                    "session_id": uid,
                                    "resposta": resposta_transferencia,
                                    "pensamento": "Aditivo de transferência gerado com sucesso!",
                                    "pdf_url": download_path,
                                    "filename": filename,
                                    "download_link": download_link,
                                    "perfil_detectado": historico_conversas[uid].get(
                                        "perfil", "neutro"
                                    ),
                                    "contexto": historico_conversas[uid].get(
                                        "contexto", {}
                                    ),
                                    "status": "sucesso",
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )
                        else:
                            logger.warning(
                                f"âŒ Erro ao gerar PDF de transferência: {pdf_result.get('error')}"
                            )

                    # Fallback: gerar documento genÃ©rico se nÃ£o conseguir usar o gerador especializado
                    conteudo_lines.append("[DOCUMENTO_OFICIAL]")
                    conteudo_lines.append("ADITIVO DE TRANSFERÃŠNCIA:")
                    conteudo_lines.append(
                        f"Nome: {nome_transfer or '___________________________'}"
                    )
                    conteudo_lines.append(f"CPF: {cpf_transfer or '____.___.___-__'}")
                    conteudo_lines.append(
                        f"Local de Origem: {local_origem or '(Não informado)'}"
                    )
                    conteudo_lines.append(
                        f"Novo Local: {local_destino or '(Não informado)'}"
                    )
                    conteudo_lines.append(f"Data da TransferÃªncia: {data_transfer}")

                else:
                    # Fallback: gerar pequeno sumÃ¡rio baseado na solicitaÃ§Ã£o
                    conteudo_lines.append("[DOCUMENTO_OFICIAL]")
                    conteudo_lines.append("SUMÃRIO EXECUTIVO:")
                    conteudo_lines.append(f"SolicitaÃ§Ã£o: {msg_limpa}")

                conteudo_pdf = "\n\n".join(conteudo_lines)

                arquivo_id = f"{tipo_doc}_{uid[:8]}_{int(time.time())}.pdf"
                metadata = {
                    "cliente": "Consulta Online",
                    "protocolo": uid,
                    "data_consulta": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "pergunta_usuario": msg_limpa[:200],
                    "tipo_documento": tipo_doc,
                    # Indica ao gerador que deve respeitar apenas campos explÃ­citos
                    # fornecidos pelo cliente e nÃ£o efetuar auto-preenchimento.
                    "only_explicit": True,
                }
                # Incluir campos explÃ­citos detectados na metadata para que o gerador
                # profissional possa priorizÃ¡-los (nÃ£o preencher automaticamente outros)
                if nome_ex:
                    metadata["nome"] = nome_ex
                if cpf_ex:
                    metadata["cp"] = cpf_ex
                if salario_ex:
                    metadata["salario"] = salario_ex

                # --- NOVA LÃ“GICA: exigir confirmaÃ§Ã£o explÃ­cita antes de gerar ---
                # Se o cliente jÃ¡ confirmou (campo 'confirmado' no payload ou respondeu 'sim'), gerar.
                # Pequena extensÃ£o: aceitar 'force_quick_path' no payload para forÃ§ar geraÃ§Ã£o imediata
                force_quick = bool(dados.get("force_quick_path", False))
                confirmado_flag = bool(dados.get("confirmado", False)) or force_quick
                simple_confirm = bool(
                    re.match(
                        r"^\s*(sim|s|confirmo|confirmar)\s*$", msg_limpa, re.IGNORECASE
                    )
                )

                # Se jÃ¡ existe uma solicitaÃ§Ã£o pendente e o usuÃ¡rio confirmou agora, usar os dados pendentes
                pending = historico_conversas[uid].get("pending_generation")
                if pending and (confirmado_flag or simple_confirm):
                    # usar conteÃºdo e metadata armazenados
                    arquivo_id = pending.get("arquivo_id")
                    conteudo_pdf = pending.get("conteudo_pd")
                    metadata = pending.get("metadata")
                    # remover pendÃªncia
                    historico_conversas[uid].pop("pending_generation", None)
                    # Tentar usar worker assÃ­ncrono (se disponÃ­vel) e aguardar breve conclusÃ£o
                    try:
                        from contabil_agente.services.document_service import (
                            enqueue_generate,
                            get_task_status,
                        )

                        job_id = enqueue_generate(arquivo_id, conteudo_pdf, metadata)
                        gerou = False
                        for _ in range(10):
                            st = get_task_status(job_id)
                            if st and st.get("status") == "done" and st.get("ok"):
                                gerou = True
                                break
                            if st and st.get("status") == "failed":
                                gerou = False
                                break
                            time.sleep(0.5)
                    except Exception:
                        gerou = construir_pdf_profissional(
                            arquivo_id, conteudo_pdf, metadata
                        )
                    if gerou:
                        download_path = f"/download/{arquivo_id}"
                        pdf_url = download_path
                        download_link = request.host_url.rstrip("/") + download_path
                        logger.info(f"âœ… PDF gerado (confirmado): {arquivo_id}")
                        resposta_final = f"Pronto â€” gerei o documento e jÃ¡ deixei o link para download: {download_link}"
                        historico_conversas[uid]["messages"].append(
                            {"role": "assistant", "content": resposta_final}
                        )
                        return jsonify(
                            {
                                "session_id": uid,
                                "resposta": resposta_final,
                                "pensamento": "",
                                "pdf_url": pdf_url,
                                "download_link": download_link,
                                "perfil_detectado": historico_conversas[uid]["perfil"],
                                "contexto": historico_conversas[uid]["contexto"],
                                "status": "sucesso",
                                "timestamp": datetime.now().isoformat(),
                            }
                        )
                    else:
                        logger.warning("âŒ Falha ao gerar PDF apÃ³s confirmaÃ§Ã£o")
                        # continuar para a geraÃ§Ã£o via modelo como fallback
                else:
                    # NÃ£o confirmado ainda â€” armazenar solicitaÃ§Ã£o pendente e pedir confirmaÃ§Ã£o
                    arquivo_id_pending = f"{tipo_doc}_{uid[:8]}_{int(time.time())}.pdf"
                    pending_payload = {
                        "arquivo_id": arquivo_id_pending,
                        "conteudo_pdf": conteudo_pdf,
                        "metadata": metadata,
                    }
                    historico_conversas[uid]["pending_generation"] = pending_payload

                    # Resposta mais humana e clara pedindo confirmaÃ§Ã£o
                    confirm_message = (
                        f"Entendi â€” vocÃª quer que eu gere o {tipo_doc} agora com os dados que vocÃª forneceu? \n"
                        "Se sim, responda apenas 'SIM' ou envie {\"confirmado\": true} no prÃ³ximo envio.\n"
                        "Se desejar corrigir algum dado, escreva as alteraÃ§Ãµes antes de confirmar."
                    )
                    historico_conversas[uid]["messages"].append(
                        {"role": "assistant", "content": confirm_message}
                    )
                    return jsonify(
                        {
                            "session_id": uid,
                            "resposta": confirm_message,
                            "pensamento": "",
                            "needs_confirmation": True,
                            "perfil_detectado": historico_conversas[uid]["perfil"],
                            "contexto": historico_conversas[uid]["contexto"],
                            "status": "confirmar",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
            except Exception as e:
                logger.error(f"Erro no gerador direto de PDF: {e}", exc_info=True)
                # DEBUG: registrar exceÃ§Ã£o via logger em vez de arquivo local
                logger.exception("EXCEPTION no gerador direto de PDF: %s", e)

        # ===== INTEGRAÃ‡ÃƒO COM MÃ“DULO INTELLIGENCE =====
        # Processar com orchestrator, TaxEngine, Compliance e Audit
        intelligence_context = {}

        if INTELLIGENCE_AVAILABLE:
            try:
                # Detectar se mensagem requer processamento de inteligÃªncia
                msg_lower = msg_limpa.lower()
                requer_calculo = bool(
                    re.search(
                        r"\b(calcul[aeo]r?|quanto|valor|total|rescis|ferias|fÃ©rias|13|decimo|inss|fgts|imposto)\b",
                        msg_lower,
                    )
                )

                if requer_calculo:
                    # Audit: registrar entrada
                    audit = get_forensic_audit()
                    audit_id = str(uuid.uuid4())
                    if audit:
                        try:
                            audit.record(
                                request_id=audit_id,
                                session_id=uid,
                                input_sanitized={"mensagem": msg_limpa[:200]},
                                output={},
                            )
                            intelligence_context["audit_id"] = audit_id
                        except Exception as e:
                            logger.debug(f"Audit record falhou: {e}")

                    # Extrair valores monetÃ¡rios para cÃ¡lculo
                    valores = re.findall(r"R?\$?\s*([\d.,]+)", msg_limpa)
                    salario = None
                    if valores:
                        try:
                            salario = float(
                                valores[0].replace(".", "").replace(",", ".")
                            )
                        except:
                            pass

                    # Extrair meses trabalhados da mensagem
                    meses_match = re.search(r"(\d+)\s*mes", msg_lower)
                    meses_trabalhados = int(meses_match.group(1)) if meses_match else 12

                    # TaxEngine: calcular valores trabalhistas completos
                    if salario:
                        tax_engine = get_tax_engine()
                        if tax_engine:
                            try:
                                calc_result = tax_engine.calculate(
                                    {
                                        "amount": salario,
                                        "date": datetime.now().isoformat(),
                                        "meses_trabalhados": meses_trabalhados,
                                        "meses_empresa": meses_trabalhados,
                                    }
                                )
                                intelligence_context["calculo"] = calc_result
                                logger.info(
                                    f"âœ… TaxEngine: calculou valores para salÃ¡rio R$ {salario} ({meses_trabalhados} meses)"
                                )
                            except Exception as e:
                                logger.debug(f"TaxEngine falhou: {e}")

                    # Compliance: validar contexto
                    compliance = get_compliance_checker()
                    if compliance:
                        try:
                            comp_result = compliance.validate(contexto_negocio)
                            intelligence_context["compliance"] = comp_result
                        except Exception as e:
                            logger.debug(f"Compliance falhou: {e}")

                    # Adicionar contexto de inteligÃªncia ao histÃ³rico para o Groq
                    if intelligence_context:
                        # Construir mensagem de sistema adicional com dados calculados
                        dados_calculados = []

                        if "calculo" in intelligence_context:
                            calc = intelligence_context["calculo"]
                            dados_calculados.append(
                                f"ðŸ“Š CÃLCULOS REALIZADOS PELO SISTEMA:"
                            )
                            if isinstance(calc, dict):
                                for key, value in calc.items():
                                    if isinstance(value, (int, float)):
                                        dados_calculados.append(
                                            f"  â€¢ {key}: R$ {value:,.2f}".replace(
                                                ",", "X"
                                            )
                                            .replace(".", ",")
                                            .replace("X", ".")
                                        )
                                    else:
                                        dados_calculados.append(f"  â€¢ {key}: {value}")

                        if "compliance" in intelligence_context:
                            comp = intelligence_context["compliance"]
                            if isinstance(comp, dict) and comp.get("alerts"):
                                dados_calculados.append(
                                    f"âš ï¸ ALERTAS DE COMPLIANCE: {comp['alerts']}"
                                )

                        # Injetar dados calculados como mensagem de sistema para o Groq usar
                        if dados_calculados:
                            intelligence_system_msg = (
                                "[DADOS CALCULADOS PELO SISTEMA - USE ESTES VALORES NA RESPOSTA]\n"
                                + "\n".join(dados_calculados)
                                + "\n\nIMPORTANTE: Use EXATAMENTE estes valores calculados pelo sistema na sua resposta. "
                                "NÃ£o invente nÃºmeros, use apenas os dados acima."
                            )
                            # Adicionar como mensagem de sistema no histÃ³rico temporariamente
                            historico_conversas[uid]["messages"].append(
                                {"role": "system", "content": intelligence_system_msg}
                            )
                            logger.info(
                                f"âœ… Dados de inteligÃªncia injetados no contexto Groq"
                            )

                        historico_conversas[uid][
                            "intelligence_context"
                        ] = intelligence_context
                        logger.info(
                            f"âœ… Intelligence context adicionado: {list(intelligence_context.keys())}"
                        )

            except Exception as e:
                logger.warning(f"âš ï¸ Erro no processamento de intelligence: {e}")

        # Chamada para o modelo Groq com verificaÃ§Ãµes
        groq_client = get_groq_client()
        groq_diagnostic = None
        if groq_client is None:
            # Em vez de retornar 503 (que causa erro no frontend), fornecer um
            # fallback local minimamente Ãºtil para manter a conversa funcional.
            logger.warning(
                "GROQ client nÃ£o disponÃ­vel. Usando fallback local de resposta (GROQ_UNAVAILABLE)."
            )

            # Coletar diagnÃ³stico curto para retorno ao cliente (sem expor segredos)
            try:
                # Testar se o pacote 'groq' Ã© importÃ¡vel sem manter uma referÃªncia nÃ£o utilizada
                import importlib

                importlib.import_module("groq")

                # Se importou, mas ainda nÃ£o hÃ¡ cliente, verificar se chave estÃ¡ presente
                if not os.getenv("GROQ_API_KEY"):
                    groq_diagnostic = {
                        "issue": "missing_env",
                        "detail": "GROQ_API_KEY nÃ£o encontrada no ambiente",
                    }
                else:
                    groq_diagnostic = {
                        "issue": "client_init_failed",
                        "detail": "Groq importado e GROQ_API_KEY presente, mas cliente nÃ£o pÃ´de ser inicializado",
                    }
            except Exception as e:
                groq_diagnostic = {"issue": "import_error", "detail": str(e)}

            # Resposta de fallback simples â€” escrita de forma a orientar o usuÃ¡rio
            # e manter compatibilidade com o restante do fluxo (PDF, confirmaÃ§Ã£o, etc.).
            resposta_bruta = (
                "OlÃ¡ â€” no momento o serviÃ§o de geraÃ§Ã£o de texto estÃ¡ indisponÃ­vel. "
                "Posso ajudar com informaÃ§Ãµes baseadas no meu conhecimento interno. "
                "Se desejar que eu gere um documento, peÃ§a explicitamente e confirme enviando 'SIM' ou {\"confirmado\": true}."
            )

        else:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=historico_conversas[uid]["messages"],
                temperature=0.3,  # Balance entre criatividade e precisÃ£o
                max_tokens=1500,
                top_p=0.9,
            )

            resposta_bruta = completion.choices[0].message.content
        pdf_url = None
        pensamento = ""

        # Extrair pensamento interno
        pensamento_match = re.search(
            r"<pensamento>(.*?)</pensamento>", resposta_bruta, re.DOTALL
        )
        if pensamento_match:
            pensamento = pensamento_match.group(1).strip()
            resposta_bruta = re.sub(
                r"<pensamento>.*?</pensamento>", "", resposta_bruta, flags=re.DOTALL
            ).strip()

        # Processar geraÃ§Ã£o de documento oficial
        # 1. Verificar marcador manual [DOCUMENTO_OFICIAL]
        # 2. OU detectar automaticamente baseado em contexto
        deve_gerar_pdf = (
            "[DOCUMENTO_OFICIAL]" in resposta_bruta
            or deve_gerar_pdf_automaticamente(msg_limpa, resposta_bruta)
        )

        if deve_gerar_pdf:
            resposta_final = resposta_bruta.replace("[DOCUMENTO_OFICIAL]", "").strip()

            # Extrair sumÃ¡rio executivo se existir, caso contrÃ¡rio usa resposta completa
            sumario_match = re.search(
                r"\[SUMÃRIO_EXECUTIVO\](.*?)\[FIM_SUMÃRIO\]", resposta_final, re.DOTALL
            )
            conteudo_pdf = (
                sumario_match.group(1).strip() if sumario_match else resposta_final
            )

            # Gerar nome de arquivo descritivo baseado no tipo de consulta
            timestamp = int(time.time())
            tipo_doc = "consulta"

            # Detectar tipo de documento pela mensagem
            msg_lower = msg_limpa.lower()
            if "rescis" in msg_lower or "demis" in msg_lower:
                tipo_doc = "rescisao"
            elif "ferias" in msg_lower or "fÃ©rias" in msg_lower:
                tipo_doc = "ferias"
            elif "13" in msg_lower or "decimo" in msg_lower:
                tipo_doc = "decimo_terceiro"
            elif "folha" in msg_lower or "pagamento" in msg_lower:
                tipo_doc = "folha_pagamento"
            elif "imposto" in msg_lower or "irp" in msg_lower or "irr" in msg_lower:
                tipo_doc = "impostos"
            elif "inss" in msg_lower or "previdencia" in msg_lower:
                tipo_doc = "inss"
            elif "fgts" in msg_lower:
                tipo_doc = "fgts"

            arquivo_id = f"{tipo_doc}_{uid[:8]}_{timestamp}.pdf"

            # Metadados completos incluindo pergunta original
            metadata = {
                "cliente": "Consulta Online",
                "protocolo": uid,
                "data_consulta": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "pergunta_usuario": msg_limpa[:200],  # Limitar tamanho
                "tipo_documento": tipo_doc,
            }

            # Exigir confirmaÃ§Ã£o tambÃ©m nesta via (geraÃ§Ã£o a partir da resposta do modelo)
            # Suporta 'force_quick_path' para pular confirmaÃ§Ã£o quando necessÃ¡rio
            force_quick = bool(dados.get("force_quick_path", False))
            confirmado_flag = bool(dados.get("confirmado", False)) or force_quick
            simple_confirm = bool(
                re.match(
                    r"^\s*(sim|s|confirmo|confirmar)\s*$", msg_limpa, re.IGNORECASE
                )
            )
            pending = historico_conversas[uid].get("pending_generation")

            if pending and (confirmado_flag or simple_confirm):
                # jÃ¡ confirmado -> gerar usando pendÃªncia
                arquivo_id = pending.get("arquivo_id")
                conteudo_pdf = pending.get("conteudo_pd")
                metadata = pending.get("metadata")
                historico_conversas[uid].pop("pending_generation", None)
                # tentar worker assÃ­ncrono primeiro
                try:
                    from contabil_agente.services.document_service import (
                        enqueue_generate,
                        get_task_status,
                    )

                    job_id = enqueue_generate(arquivo_id, conteudo_pdf, metadata)
                    ok_generated = False
                    for _ in range(10):
                        st = get_task_status(job_id)
                        if st and st.get("status") == "done" and st.get("ok"):
                            ok_generated = True
                            break
                        if st and st.get("status") == "failed":
                            ok_generated = False
                            break
                        time.sleep(0.5)
                except Exception:
                    ok_generated = construir_pdf_profissional(
                        arquivo_id, conteudo_pdf, metadata
                    )

                if ok_generated:
                    download_path = f"/download/{arquivo_id}"
                    pdf_url = download_path
                    download_link = request.host_url.rstrip("/") + download_path
                    logger.info(
                        f"âœ… PDF profissional gerado (confirmado): {arquivo_id} | Tipo: {tipo_doc}"
                    )
                    historico_conversas[uid]["messages"].append(
                        {
                            "role": "assistant",
                            "content": f"Documento pronto. Baixe aqui: {download_link}",
                        }
                    )
                else:
                    logger.error(f"âŒ Falha ao gerar PDF: {arquivo_id}")
            elif confirmado_flag or simple_confirm:
                # confirmado direto na mesma requisiÃ§Ã£o -> gerar (usar worker quando possÃ­vel)
                try:
                    from contabil_agente.services.document_service import (
                        enqueue_generate,
                        get_task_status,
                    )

                    job_id = enqueue_generate(arquivo_id, conteudo_pdf, metadata)
                    ok_generated = False
                    for _ in range(10):
                        st = get_task_status(job_id)
                        if st and st.get("status") == "done" and st.get("ok"):
                            ok_generated = True
                            break
                        if st and st.get("status") == "failed":
                            ok_generated = False
                            break
                        time.sleep(0.5)
                except Exception:
                    ok_generated = construir_pdf_profissional(
                        arquivo_id, conteudo_pdf, metadata
                    )

                if ok_generated:
                    download_path = f"/download/{arquivo_id}"
                    pdf_url = download_path
                    download_link = request.host_url.rstrip("/") + download_path
                    logger.info(
                        f"âœ… PDF profissional gerado: {arquivo_id} | Tipo: {tipo_doc}"
                    )
                    historico_conversas[uid]["messages"].append(
                        {
                            "role": "assistant",
                            "content": f"Documento pronto. Baixe aqui: {download_link}",
                        }
                    )
                else:
                    logger.error(f"âŒ Falha ao gerar PDF: {arquivo_id}")
            else:
                # armazenar pendÃªncia e pedir confirmaÃ§Ã£o ao usuÃ¡rio
                historico_conversas[uid]["pending_generation"] = {
                    "arquivo_id": arquivo_id,
                    "conteudo_pdf": conteudo_pdf,
                    "metadata": metadata,
                }
                confirm_message = (
                    f"Posso gerar um {tipo_doc} com base na resposta que preparei. Deseja que eu gere o PDF agora?\n"
                    "Responda 'SIM' para confirmar ou envie {\"confirmado\": true} no prÃ³ximo envio."
                )
                historico_conversas[uid]["messages"].append(
                    {"role": "assistant", "content": confirm_message}
                )
                return jsonify(
                    {
                        "session_id": uid,
                        "resposta": confirm_message,
                        "pensamento": pensamento,
                        "needs_confirmation": True,
                        "perfil_detectado": historico_conversas[uid]["perfil"],
                        "contexto": historico_conversas[uid]["contexto"],
                        "status": "confirmar",
                        "timestamp": datetime.now().isoformat(),
                    }
                )
        else:
            resposta_final = resposta_bruta

        # Adicionar resposta da IA ao histÃ³rico
        historico_conversas[uid]["messages"].append(
            {"role": "assistant", "content": resposta_bruta}
        )

        # Gerenciar tamanho do histÃ³rico (manter Ãºltimos 15 mensagens + system prompt)
        if len(historico_conversas[uid]["messages"]) > 16:
            historico_conversas[uid]["messages"] = [
                historico_conversas[uid]["messages"][0]
            ] + historico_conversas[uid]["messages"][
                -15:
            ]  # system prompt

        resp_payload = {
            "session_id": uid,
            "resposta": resposta_final,
            "pensamento": pensamento,
            "pdf_url": pdf_url,
            "perfil_detectado": historico_conversas[uid]["perfil"],
            "contexto": historico_conversas[uid]["contexto"],
            "status": "sucesso",
            "timestamp": datetime.now().isoformat(),
            # Contexto de inteligÃªncia (se disponÃ­vel)
            "intelligence_context": historico_conversas[uid].get(
                "intelligence_context"
            ),
            "intelligence_status": {
                "available": INTELLIGENCE_AVAILABLE,
                "orchestrator": get_intelligence_orchestrator() is not None,
                "tax_engine": get_tax_engine() is not None,
                "compliance": get_compliance_checker() is not None,
                "audit": get_forensic_audit() is not None,
            },
        }

        # Incluir diagnÃ³stico leve quando disponÃ­vel (ex.: Groq indisponÃ­vel)
        if "groq_diagnostic" in locals() and groq_diagnostic:
            resp_payload["diagnostic"] = groq_diagnostic

        return jsonify(resp_payload)

    except Exception as e:
        logger.error(f"Erro no processamento do chat: {e}", exc_info=True)
        # Retornar detalhes temporÃ¡rios para debugging local
        return (
            jsonify(
                {
                    "erro": "Erro interno no processamento da consulta",
                    "status": "erro",
                    "codigo": "INTERNAL_ERROR",
                    "detalhes": str(e),
                }
            ),
            500,
        )


@chat_blueprint.route("/api/health", methods=["GET"])
def health_check():
    """Endpoint de verificaÃ§Ã£o de saÃºde do sistema"""
    # Basic payload
    payload = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "sessoes_ativas": len(historico_conversas),
        "modelo": "llama-3.3-70b-versatile",
    }

    # 1) Check GROQ circuit/unavailability from refactored module if present
    try:
        from contabil_agente.routes import chat_refactored as chat_ref

        groq_until = getattr(chat_ref, "_groq_unavailable_until", 0)
        if groq_until and time.time() < float(groq_until):
            return (
                jsonify(
                    {
                        "status": "degraded",
                        "codigo": "GROQ_UNAVAILABLE",
                        "mensagem": "Groq indisponÃ­vel temporariamente devido a erro externo",
                        "unavailable_until": datetime.fromtimestamp(
                            float(groq_until)
                        ).isoformat(),
                    }
                ),
                503,
            )
    except Exception:
        # ignore import errors and continue
        pass

    # 2) Validate GROQ API key format to preflight obvious auth issues
    try:
        groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
        if not groq_key or not re.match(r"^gsk_[A-Za-z0-9_-]{10,}$", groq_key):
            return (
                jsonify(
                    {
                        "status": "degraded",
                        "codigo": "GROQ_INVALID_KEY",
                        "mensagem": "GROQ API key ausente ou com formato invÃ¡lido",
                    }
                ),
                401,
            )
    except Exception:
        pass

    # For probes and frontend health checks, return a minimal stable JSON payload
    # Also ensure the Groq circuit is not left open from stale state: if health is OK,
    # reset the circuit in the refactored module to avoid false positives.
    try:
        from contabil_agente.routes import chat_refactored as chat_ref

        try:
            if getattr(chat_ref, "_groq_unavailable_until", 0):
                # if the stored value is in the past or we have a present healthy status, clear it
                if time.time() > float(getattr(chat_ref, "_groq_unavailable_until", 0)):
                    chat_ref._groq_unavailable_until = 0
                else:
                    # If still set but overall system health is OK, be conservative and clear it
                    chat_ref._groq_unavailable_until = 0
        except Exception:
            pass
    except Exception:
        pass

    return jsonify({"status": "ok"})


# Ensure /api/health and /api/chat are exempt from the global rate limiter so probes
# and internal bulk tests never receive HTML 429 responses. This is safe to call repeatedly.
try:
    from contabil_agente import app as _app_mod

    limiter_obj = getattr(_app_mod, "limiter", None)
    if limiter_obj is not None:
        # Exempt health endpoint
        try:
            limiter_obj.exempt(health_check)
        except Exception:
            pass
        # Exempt chat processing endpoint
        try:
            limiter_obj.exempt(processar_chat)
        except Exception:
            pass
except Exception:
    # Best-effort: try importing limiter directly from app module
    try:
        from contabil_agente.app import limiter as _lim

        try:
            _lim.exempt(health_check)
        except Exception:
            pass
        try:
            _lim.exempt(processar_chat)
        except Exception:
            pass
    except Exception:
        pass


@chat_blueprint.route("/api/debug/session/<session_id>", methods=["GET"])
def debug_session(session_id):
    """Endpoint de debug para visualizar histÃ³rico de sessÃ£o"""
    if session_id not in historico_conversas:
        return (
            jsonify(
                {
                    "erro": "sessÃ£o nÃ£o encontrada",
                    "sessoes_disponiveis": list(historico_conversas.keys()),
                }
            ),
            404,
        )

    sessao = historico_conversas[session_id]
    # Mostrar apenas role e preview do content (para nÃ£o poluir)
    messages_preview = []
    for msg in sessao.get("messages", []):
        preview = (
            msg.get("content", "")[:100] + "..."
            if len(msg.get("content", "")) > 100
            else msg.get("content", "")
        )
        messages_preview.append({"role": msg.get("role"), "content_preview": preview})

    return jsonify(
        {
            "session_id": session_id,
            "total_messages": len(sessao.get("messages", [])),
            "messages": messages_preview,
            "contexto": sessao.get("contexto"),
            "perfil": sessao.get("perfil"),
            "pending_generation": sessao.get("pending_generation") is not None,
        }
    )


@chat_blueprint.route("/api/debug/groq-key", methods=["GET"])
def groq_key_status():
    """Endpoint de diagnÃ³stico seguro para o estado de `GROQ_API_KEY`.

    Retorna apenas informaÃ§Ãµes nÃ£o sensÃ­veis: se a chave estÃ¡ presente,
    seu comprimento e uma versÃ£o mascarada (apenas Ãºltimos 4 caracteres).
    NÃ£o revela o valor completo.
    """
    try:
        key = os.getenv("GROQ_API_KEY")
    except Exception:
        key = None

    # Verificar se o pacote groq pode ser importado (sem inicializar cliente)
    try:
        # Use importlib to test if the package can be imported without
        # assigning an unused local variable (avoids linter F401).
        import importlib

        importlib.import_module("groq")
        groq_importable = True
    except Exception:
        groq_importable = False

    if not key:
        return (
            jsonify(
                {
                    "present": False,
                    "message": "GROQ_API_KEY nÃ£o encontrada no ambiente",
                    "groq_importable": groq_importable,
                }
            ),
            200,
        )

    # Mascarar: mostrar apenas os Ãºltimos 4 caracteres
    try:
        masked = ("*" * max(0, len(key) - 4)) + key[-4:]
    except Exception:
        masked = "****"

    return (
        jsonify(
            {
                "present": True,
                "length": len(key),
                "masked": masked,
                "groq_importable": groq_importable,
            }
        ),
        200,
    )


@chat_blueprint.route("/api/session/<session_id>", methods=["DELETE"])
def encerrar_sessao(session_id):
    """Encerra uma sessÃ£o especÃ­fica"""
    if session_id in historico_conversas:
        del historico_conversas[session_id]
        return jsonify({"status": "sessÃ£o encerrada"})
    return jsonify({"erro": "sessÃ£o nÃ£o encontrada"}), 404


@chat_blueprint.route("/api/transcribe", methods=["POST"])
def transcrever_audio():
    """Transcreve Ã¡udio usando Whisper da Groq"""
    try:
        if "audio" not in request.files:
            return jsonify({"erro": "Nenhum arquivo de Ã¡udio enviado"}), 400

        audio_file = request.files["audio"]
        session_id = request.form.get("session_id", str(uuid.uuid4()))

        # Salvar temporariamente
        temp_audio_path = os.path.join(
            UPLOAD_FOLDER, f"audio_{session_id}_{int(time.time())}.webm"
        )
        audio_file.save(temp_audio_path)

        logger.info(f"ðŸŽ¤ Processando Ã¡udio: {temp_audio_path}")

        # Transcrever com Whisper da Groq
        with open(temp_audio_path, "rb") as file:
            transcription = get_groq_client().audio.transcriptions.create(
                file=(os.path.basename(temp_audio_path), file.read()),
                model="whisper-large-v3",
                language="pt",
                response_format="json",
            )

        texto_transcrito = transcription.text

        # Limpar arquivo temporÃ¡rio
        try:
            os.remove(temp_audio_path)
        except OSError as e:
            logger.warning(f"NÃ£o foi possÃ­vel remover arquivo temporÃ¡rio: {e}")

        logger.info(f"âœ… Ãudio transcrito: {texto_transcrito[:100]}...")

        return jsonify(
            {
                "texto_transcrito": texto_transcrito,
                "session_id": session_id,
                "status": "sucesso",
            }
        )

    except Exception as e:
        logger.error(f"Erro ao transcrever Ã¡udio: {e}", exc_info=True)
        return jsonify({"erro": "Erro ao processar Ã¡udio", "detalhes": str(e)}), 500


@chat_blueprint.route("/api/analyze-documents", methods=["POST"])
def analisar_documentos():
    """Analisa documentos contÃ¡beis enviados (PDF, Excel, Imagens)"""
    try:
        if "files" not in request.files:
            return jsonify({"erro": "Nenhum arquivo enviado"}), 400

        files = request.files.getlist("files")
        session_id = request.form.get("session_id", str(uuid.uuid4()))

        analises = []
        textos_extraidos = []

        for file in files:
            if file.filename == "":
                continue

            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, f"{session_id}_{filename}")
            file.save(filepath)

            logger.info(f"ðŸ“„ Analisando documento: {filename}")

            # Extrair texto baseado no tipo de arquivo
            texto_extraido = ""
            tipo_documento = "desconhecido"

            if filename.lower().endswith(".pd"):
                texto_extraido, tipo_documento = analisar_pdf(filepath)
            elif filename.lower().endswith((".jpg", ".jpeg", ".png")):
                texto_extraido, tipo_documento = analisar_imagem(filepath)
            elif filename.lower().endswith((".xlsx", ".xls", ".csv")):
                texto_extraido, tipo_documento = analisar_planilha(filepath)

            if texto_extraido:
                analises.append(
                    {
                        "arquivo": filename,
                        "tipo": tipo_documento,
                        "conteudo": texto_extraido[:500],  # Limitar tamanho
                    }
                )
                textos_extraidos.append(
                    f"**{filename}** ({tipo_documento}):\\n{texto_extraido}"
                )

            # Limpar arquivo apÃ³s anÃ¡lise
            try:
                os.remove(filepath)
            except OSError as e:
                logger.warning(
                    f"NÃ£o foi possÃ­vel remover arquivo temporÃ¡rio {filepath}: {e}"
                )

        # Gerar anÃ¡lise inteligente com IA
        if textos_extraidos:
            prompt_analise = f"""VocÃª Ã© um contador especialista. Analise os seguintes documentos:

{chr(10).join(textos_extraidos)}

ForneÃ§a:
1. Resumo executivo dos documentos
2. Valores monetÃ¡rios identificados
3. Alertas fiscais/trabalhistas importantes
4. PrÃ³ximas aÃ§Ãµes recomendadas

Seja objetivo e tÃ©cnico."""

            completion = get_groq_client().chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "VocÃª Ã© um contador sÃªnior especialista em anÃ¡lise de documentos.",
                    },
                    {"role": "user", "content": prompt_analise},
                ],
                temperature=0.2,
                max_tokens=1000,
            )

            analise_completa = completion.choices[0].message.content

            # Gerar PDF se anÃ¡lise for substancial
            pdf_url = None
            if len(analise_completa) > 300:
                arquivo_id = f"analise_docs_{session_id}_{int(time.time())}.pdf"
                metadata = {
                    "cliente": "AnÃ¡lise de Documentos",
                    "protocolo": session_id,
                    "data_analise": datetime.now().strftime("%d/%m/%Y %H:%M"),
                }
                # usar worker quando disponÃ­vel
                try:
                    from contabil_agente.services.document_service import (
                        enqueue_generate,
                        get_task_status,
                    )

                    job_id = enqueue_generate(arquivo_id, analise_completa, metadata)
                    ok_generated = False
                    for _ in range(10):
                        st = get_task_status(job_id)
                        if st and st.get("status") == "done" and st.get("ok"):
                            ok_generated = True
                            break
                        if st and st.get("status") == "failed":
                            ok_generated = False
                            break
                        time.sleep(0.5)
                except Exception:
                    ok_generated = construir_pdf_profissional(
                        arquivo_id, analise_completa, metadata
                    )

                if ok_generated:
                    pdf_url = f"/download/{arquivo_id}"

            # Gerar sugestÃµes contextuais
            sugestoes = []
            if "nota fiscal" in analise_completa.lower():
                sugestoes.append("Gerar relatÃ³rio de impostos sobre compras")
                sugestoes.append("Validar crÃ©ditos de ICMS/IPI")
            if (
                "holerite" in analise_completa.lower()
                or "folha" in analise_completa.lower()
            ):
                sugestoes.append("Calcular encargos trabalhistas totais")
                sugestoes.append("Verificar recolhimento de INSS/FGTS")
            if (
                "extrato" in analise_completa.lower()
                or "banco" in analise_completa.lower()
            ):
                sugestoes.append("Reconciliar movimentaÃ§Ãµes bancÃ¡rias")
                sugestoes.append("Identificar despesas dedutÃ­veis")

            return jsonify(
                {
                    "analise": analise_completa,
                    "documentos_processados": len(files),
                    "pdf_url": pdf_url,
                    "sugestoes": sugestoes,
                    "status": "sucesso",
                    "session_id": session_id,
                }
            )
        else:
            return (
                jsonify(
                    {"erro": "NÃ£o foi possÃ­vel extrair informaÃ§Ãµes dos documentos"}
                ),
                400,
            )

    except Exception as e:
        logger.error(f"Erro ao analisar documentos: {e}", exc_info=True)
        return (
            jsonify({"erro": "Erro ao processar documentos", "detalhes": str(e)}),
            500,
        )


def analisar_pdf(filepath: str) -> tuple:
    """Extrai texto de PDF"""
    try:
        try:
            # prefer pypdf (successor of PyPDF2) to avoid deprecation warnings
            from pypdf import PdfReader as _PdfReader
        except Exception:
            try:
                # Import dinamicamente para evitar avisos do analisador estÃ¡tico
                import importlib
                import warnings

                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", category=DeprecationWarning, module="PyPDF2"
                    )
                    _pyPdf = importlib.import_module("PyPDF2")

                # Compatibilidade com versÃµes antigas/novas do PyPDF2
                _PdfReader = getattr(
                    _pyPdf, "PdfReader", getattr(_pyPdf, "PdfFileReader", None)
                )
                if _PdfReader is None:
                    raise ImportError("PyPDF2 PdfReader not found")
            except Exception:
                raise

        texto = ""
        with open(filepath, "rb") as file:
            reader = _PdfReader(file)
            # pages attribute differs between libs; try generic iteration
            try:
                pages = getattr(reader, "pages", None) or reader.pages
            except Exception:
                pages = []
            for page in pages:
                try:
                    txt = page.extract_text()
                except Exception:
                    try:
                        txt = page.extractText()
                    except Exception:
                        txt = ""
                texto += (txt or "") + "\\n"

        # Detectar tipo de documento
        tipo = "documento_generico"
        texto_lower = texto.lower()
        if "nota fiscal" in texto_lower or "nf-e" in texto_lower:
            tipo = "nota_fiscal"
        elif "holerite" in texto_lower or "contracheque" in texto_lower:
            tipo = "holerite"
        elif "extrato" in texto_lower or "banco" in texto_lower:
            tipo = "extrato_bancario"

        return texto, tipo
    except ImportError:
        logger.warning("PyPDF2 nÃ£o instalado - tentando mÃ©todo alternativo")
        return "ConteÃºdo do PDF (instale PyPDF2 para extraÃ§Ã£o completa)", "pd"
    except Exception as e:
        logger.error(f"Erro ao ler PDF: {e}")
        return f"Erro ao processar PDF: {str(e)}", "erro"


def analisar_imagem(filepath: str) -> tuple:
    """Extrai texto de imagem usando OCR bÃ¡sico"""
    try:
        # Import dinamicamente para evitar erros de lint quando o pacote nÃ£o
        # estiver instalado no ambiente de desenvolvimento.
        import importlib

        Image = importlib.import_module("PIL.Image")
        pytesseract = importlib.import_module("pytesseract")

        image = Image.open(filepath)
        texto = pytesseract.image_to_string(image, lang="por")

        tipo = "documento_escaneado"
        if "nota fiscal" in texto.lower():
            tipo = "nota_fiscal_escaneada"
        elif "recibo" in texto.lower():
            tipo = "recibo"

        return texto, tipo
    except ModuleNotFoundError:
        logger.warning("PIL/pytesseract nÃ£o instalado - anÃ¡lise bÃ¡sica de imagem")
        return (
            f"Imagem recebida: {os.path.basename(filepath)} (instale pillow e pytesseract para OCR)",
            "imagem",
        )
    except Exception as e:
        logger.error(f"Erro ao processar imagem: {e}")
        return f"Imagem: {os.path.basename(filepath)}", "imagem"


def analisar_planilha(filepath: str) -> tuple:
    """Extrai dados de planilha Excel/CSV"""
    try:
        import pandas as pd

        if filepath.endswith(".csv"):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)

        # Resumo da planilha
        resumo = f"Planilha com {len(df)} linhas e {len(df.columns)} colunas\\n"
        resumo += f"Colunas: {', '.join(df.columns.tolist())}\\n\\n"
        resumo += "Primeiras linhas:\\n"
        resumo += df.head(5).to_string()

        tipo = "planilha_dados"
        colunas_lower = " ".join(df.columns.tolist()).lower()
        if "salÃ¡rio" in colunas_lower or "funcionÃ¡rio" in colunas_lower:
            tipo = "folha_pagamento"
        elif "nota" in colunas_lower or "valor" in colunas_lower:
            tipo = "planilha_fiscal"

        return resumo, tipo
    except ImportError:
        logger.warning("pandas nÃ£o instalado - anÃ¡lise bÃ¡sica de planilha")
        return (
            f"Planilha recebida: {os.path.basename(filepath)} (instale pandas para anÃ¡lise)",
            "planilha",
        )
    except Exception as e:
        logger.error(f"Erro ao processar planilha: {e}")
        return f"Planilha: {os.path.basename(filepath)}", "planilha"


@chat_blueprint.route("/api/text-to-speech", methods=["POST"])
def text_to_speech():
    """Converte texto em Ã¡udio usando TTS"""
    try:
        dados = request.get_json()
        texto = dados.get("texto", "").strip()
        session_id = dados.get("session_id", str(uuid.uuid4()))

        if not texto:
            return jsonify({"erro": "Texto vazio"}), 400

        # Limitar tamanho do texto (TTS tem limites)
        if len(texto) > 5000:
            texto = texto[:5000] + "... [texto truncado para Ã¡udio]"

        logger.info(f"ðŸ”Š Gerando Ã¡udio TTS: {texto[:100]}...")

        # Primeiro: tentar gTTS (Google TTS)
        try:
            from gtts import gTTS

            # Gerar Ã¡udio com gTTS (Google Text-to-Speech)
            tts = gTTS(text=texto, lang="pt", slow=False)

            # Salvar em memÃ³ria
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)

            logger.info("âœ… Ãudio TTS gerado com sucesso (gTTS)")

            return (
                audio_buffer.getvalue(),
                200,
                {
                    "Content-Type": "audio/mpeg",
                    "Content-Disposition": f'inline; filename="resposta_{session_id}.mp3"',
                },
            )

        except Exception as e_gtts:
            # Não quebrar a API; tentar fallback local (pyttsx3 via ToolVoz)
            logger.warning(f"gTTS indisponível ou falhou: {e_gtts}")

            try:
                # Tentativa de fallback local usando ToolVoz (pyttsx3)
                from tools.voz_tool import ToolVoz

                voz = ToolVoz()
                if getattr(voz, "tts_engine", None) is not None:
                    tmp_path = os.path.join(TEMP_FOLDER, f"tts_{session_id}.mp3")
                    try:
                        # pyttsx3 suporta save_to_file
                        voz.tts_engine.save_to_file(texto, tmp_path)
                        voz.tts_engine.runAndWait()

                        with open(tmp_path, "rb") as f:
                            data = f.read()

                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

                        logger.info("âœ… Ãudio TTS gerado com sucesso (pyttsx3)")
                        return (
                            data,
                            200,
                            {
                                "Content-Type": "audio/mpeg",
                                "Content-Disposition": f'inline; filename="resposta_{session_id}.mp3"',
                            },
                        )
                    except Exception as e_pytt:
                        logger.warning(f"Falha ao gerar áudio via pyttsx3: {e_pytt}")
                else:
                    logger.info("ToolVoz pyttsx3 não disponível")
            except Exception as e_tool:
                logger.debug(f"Fallback ToolVoz indisponível: {e_tool}")

            # Último recurso: informar ao cliente que use o TTS do navegador
            logger.info("Retornando fallback para síntese no navegador (browser TTS)")
            return (
                jsonify(
                    {
                        "fallback": "browser",
                        "message": "TTS no servidor indisponível. Use a síntese do navegador (SpeechSynthesis).",
                    }
                ),
                200,
            )

    except Exception as e:
        logger.error(f"Erro ao gerar TTS: {e}", exc_info=True)
        return jsonify({"erro": "Erro ao gerar Ã¡udio", "detalhes": str(e)}), 500


# --- Delegar implementaÃ§Ãµes de intenÃ§Ã£o para services.intent_service quando disponÃ­vel
try:
    from services.intent_service import detectar_perfil_usuario as _det_impl
    from services.intent_service import extrair_contexto_negocio as _extr_impl
    from services.intent_service import normalizar_texto_avancado as _norm_impl

    # Substituir as implementaÃ§Ãµes locais pelas versÃµes centralizadas
    normalizar_texto_avancado = _norm_impl
    extrair_contexto_negocio = _extr_impl
    detectar_perfil_usuario = _det_impl

    logger.info(
        "Usando implementaÃ§Ãµes de services.intent_service para normalizaÃ§Ã£o e detecÃ§Ã£o de perfil"
    )
except Exception:
    # Fallback: definir implementaÃ§Ãµes mÃ­nimas se nÃ£o houver serviÃ§o centralizado
    try:
        from services.intent_service import normalizar_texto_avancado
    except Exception:

        def normalizar_texto_avancado(texto: str) -> str:
            """Fallback: normalizaÃ§Ã£o minimal de texto"""
            return texto.strip().lower()

    logger.info(
        "Mantendo implementaÃ§Ãµes locais/fallback de normalizaÃ§Ã£o e detecÃ§Ã£o de perfil (services.intent_service indisponÃ­vel)"
    )
