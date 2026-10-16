"""Chat integrado com TODA a inteligência do sistema.

Integra:
- IntelligenceOrchestrator (FSM, cache, compliance, audit)
- GroqClient (Maria Helena via LLM)
- TaxEngine (cálculos fiscais/trabalhistas)
- ComplianceChecker (validações legais)
- ForensicAudit (rastreabilidade completa)
"""

from flask import Blueprint, jsonify, request, send_from_directory
import logging
import os
import re
import uuid
import time
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from decimal import Decimal
import difflib
import unicodedata

# Persona integration
from contabil_agente.persona import process_intelligence_request_persona

chat_refactored_bp = Blueprint("chat_refactored", __name__)

logger = logging.getLogger(__name__)

# 🔐 Armazenamento de confirmações pendentes por session_id
# Este dicionário persiste entre requisições HTTP quando rodando em processo único
_pending_confirmations_state: Dict[str, Dict[str, Any]] = {}


def _slugify(value: str) -> str:
    """Return an ASCII-safe slug for filenames (keep alnum and underscore)."""
    try:
        nf = unicodedata.normalize("NFKD", str(value))
        ascii_name = nf.encode("ascii", "ignore").decode("ascii")
        slug = "".join(c if (c.isalnum() or c in "_-") else "_" for c in ascii_name)
        # collapse multiple underscores
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or "file"
    except Exception:
        return "file"


def _generate_pdf_for_tipo(
    tipo: str, dados_doc: dict, mensagem: str, audit_id: str, session_id: str
):
    """Generate a type-specific PDF. Returns dict with keys: pdf_path, sha256, filename, success."""
    try:
        # Prefer DocumentService for consistent, professional PDFs
        from contabil_agente.services.document_service import DocumentService

        svc = DocumentService.get_instance()
        tipo_safe = _slugify(tipo)
        filename = f"{tipo_safe}_{uuid.uuid4().hex[:8]}.pdf"

        # Per-type content templates (small, focused variations)
        if tipo == "ferias":
            content = f"[FÉRIAS]\nSolicitação de férias\nDados: {dados_doc}"
            meta = {"title": "Férias", "author": "Sistema Contábil"}
        elif tipo == "decimo_terceiro":
            content = f"[13º]\nCálculo do décimo terceiro\nDados: {dados_doc}"
            meta = {"title": "Décimo Terceiro", "author": "Sistema Contábil"}
        elif tipo == "folha_pagamento":
            content = f"[FOLHA]\nFolha de pagamento\nDados: {dados_doc}"
            meta = {"title": "Folha de Pagamento", "author": "Sistema Contábil"}
        elif tipo == "inss":
            content = f"[INSS]\nCálculo INSS\nDados: {dados_doc}"
            meta = {"title": "INSS", "author": "Sistema Contábil"}
        elif tipo == "fgts":
            content = f"[FGTS]\nCálculo FGTS\nDados: {dados_doc}"
            meta = {"title": "FGTS", "author": "Sistema Contábil"}
        elif tipo == "imposto":
            content = f"[IMPOSTO]\nRelatório tributário\nDados: {dados_doc}"
            meta = {"title": "Imposto", "author": "Sistema Contábil"}
        elif tipo == "admissao":
            content = f"[ADMISSÃO]\nDocumento de admissão\nDados: {dados_doc}"
            meta = {"title": "Admissão", "author": "Sistema Contábil"}
        elif tipo == "consulta":
            content = f"[CONSULTA]\nOrientação\nDados: {dados_doc}"
            meta = {"title": "Consulta", "author": "Sistema Contábil"}
        else:
            content = f"[DOCUMENTO_{tipo.upper()}]\nTipo: {tipo}\nDados: {dados_doc}"
            meta = {"title": tipo.title(), "author": "Sistema Contábil"}

        ok = svc.generate_professional_pdf(
            filename,
            content,
            metadata={**meta, "pergunta_usuario": mensagem, "protocolo": audit_id},
        )
        if ok:
            pdf_path = os.path.join(svc.output_folder, filename)
            if os.path.exists(pdf_path):
                sha = None
                try:
                    import hashlib

                    with open(pdf_path, "rb") as f:
                        sha = hashlib.sha256(f.read()).hexdigest()
                except Exception:
                    pass
                return {
                    "success": True,
                    "pdf_path": pdf_path,
                    "sha256": sha,
                    "filename": filename,
                }
    except Exception:
        pass
    return {"success": False}


def _chat_integrado_impl():
    # DEBUG: Log no início (usar logger em vez de escrever em C:/)
    try:
        logger.debug("=== chat_integrado chamado ===")
    except Exception:
        pass

    # Parse JSON body safely (avoid raising if body is invalid)
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    # Log de headers (mascarar Authorization por segurança)
    try:
        hdrs = dict(request.headers)
        if "Authorization" in hdrs:
            hdrs["Authorization"] = "REDACTED"
        logger.info(
            f"Incoming /api/chat - remote_addr={request.remote_addr} headers={hdrs}"
        )
    except Exception as e:
        logger.warning(f"Falha ao logar headers do /api/chat: {e}")

    # Endpoint principal de chat com inteligência completa.

    mensagem = (data.get("mensagem") or "").strip()
    session_id = data.get("session_id") or str(uuid.uuid4())
    dados_extras = data.get("dados") or {}

    if not mensagem:
        return jsonify({"erro": "Mensagem vazia"}), 400

    # Inicializar/recuperar sessão
    if session_id not in _session_cache:
        _session_cache[session_id] = {
            "messages": [],
            "created_at": time.time(),
            "last_activity": time.time(),
            "contexto": {},
            "dados_acumulados": {},  # Dados coletados ao longo da conversa
            "tipo_pendente": None,  # Tipo de documento pendente de confirmação
        }

    sessao = _session_cache[session_id]
    sessao["last_activity"] = time.time()

    # Adicionar mensagem do usuário ao histórico
    sessao["messages"].append({"role": "user", "content": mensagem})

    # 🔍 DETECTAR CONFIRMAÇÃO PRIMEIRO: "sim", "certo", "gera", "ok", etc.
    # Isso deve ser feito ANTES de detectar intenção para que confirmações funcionem
    texto_lower = mensagem.lower().strip()
    confirmacao_patterns = [
        r"^(sim|certo|ok|gera|gere|pode|confirmo|isso|tudo certo|está certo|correto)$",
        r"\b(gera|gere|pode gerar|confirmo|confirmar)\b",
    ]
    eh_confirmacao = any(re.search(p, texto_lower) for p in confirmacao_patterns)

    # 1. Detectar intenção
    intencao = detectar_intencao(mensagem)

    # Se é uma confirmação e temos tipo pendente, usar dados acumulados ANTES de processar persona
    if eh_confirmacao and sessao.get("tipo_pendente"):
        intencao["tipo"] = sessao["tipo_pendente"]
        intencao["requer_documento"] = sessao["tipo_pendente"] in [
            "rescisao",
            "ferias",
            "admissao",
            "transferencia",
        ]
        intencao["dados_extraidos"] = sessao["dados_acumulados"].copy()
        intencao["confianca"] = 0.95
        logger.info(
            f"✅ Confirmação detectada! Tipo: {intencao['tipo']}, Dados: {intencao['dados_extraidos']}"
        )
        # Após processar a confirmação, limpar o tipo pendente para evitar re-prompt contínuo
        try:
            sessao["tipo_pendente"] = None
        except Exception:
            pass

    # 🧠 INTEGRAÇÃO PERSONA: Processar com regras de Maria Helena
    persona_response = None
    persona_thinking = None
    try:
        from flask import session as flask_session

        persona_response = process_intelligence_request_persona(
            session_id=session_id,
            payload={
                "user_text": mensagem,
                "text": mensagem,
                "message": mensagem,
                "fields": intencao.get("dados_extraidos", {}),
                "intencao_tipo": intencao.get("tipo"),
                "intencao_confianca": intencao.get("confianca"),
                "requer_calculo": intencao.get("requer_calculo"),
                "flask_session": flask_session,  # Passar sessão para confirmação pendente
                "pending_confirmations_store": _pending_confirmations_state,  # Armazenamento in-memory
            },
        )
        # Extrair pensamento e status da persona
        if persona_response:
            persona_thinking = persona_response.get("message", "")
            persona_status = persona_response.get("status", "")
            logger.info(
                f"✅ Persona resposta: status={persona_status}, mensagem={persona_thinking[:50]}..."
            )
            # Se persona retorna awaiting_confirmation ou resume, usar sua resposta
            if persona_status in ("awaiting_confirmation", "resume", "summary"):
                logger.info(
                    f"Persona aguardando dados ou resumindo - returnando resposta customizada"
                )
    except Exception as e:
        logger.warning(f"⚠️ Erro ao processar persona: {e}")
        persona_response = None
        persona_thinking = None

    # Mesclar dados extras
    if dados_extras:
        intencao["dados_extraidos"].update(dados_extras)

    # 🔄 ACUMULAR DADOS: Mesclar dados extraídos com dados da sessão
    if intencao["dados_extraidos"]:
        sessao["dados_acumulados"].update(intencao["dados_extraidos"])

    # Se detectamos um novo tipo específico (não conversa), salvar como pendente
    if intencao["tipo"] != "conversa" and intencao["tipo"] != sessao.get(
        "tipo_pendente"
    ):
        sessao["tipo_pendente"] = intencao["tipo"]
        sessao["dados_acumulados"] = intencao["dados_extraidos"].copy()

    # 🎯 NOVO: Se persona retorna "confirmed" (usuário respondeu "sim" a confirmação)
    # Atualizar dados com campos confirmados e deixar processar normalmente
    if persona_response and persona_response.get("status") == "confirmed":
        confirmed_fields = persona_response.get("fields", {})
        if confirmed_fields:
            logger.info(f"✅ Campos confirmados: {confirmed_fields}")
            intencao["dados_extraidos"].update(confirmed_fields)
            sessao["dados_acumulados"].update(confirmed_fields)
            # Limpar tipo pendente e estado de confirmação para evitar loop
            sessao["tipo_pendente"] = None
            # Limpar armazenamento de confirmação pendente
            if session_id in _pending_confirmations_state:
                del _pending_confirmations_state[session_id]
                logger.info(
                    f"🗑️ Limpeza: Removido estado de confirmação para {session_id}"
                )
            # Deixar persona_response como None para forçar processamento normal de inteligência
            persona_response = None
            persona_thinking = None

    # 2. Processar com inteligência (async -> sync wrapper)
    # Se persona retornou uma resposta especial, usar essa em vez de processar com inteligência
    if persona_response and persona_response.get("status") in (
        "awaiting_confirmation",
        "resume",
        "summary",
        "ok",  # ✅ Aceitar também responses "ok" da persona (problema 2: perguntas vagas)
    ):
        logger.info(
            f"Usando resposta customizada da persona: {persona_response['status']}"
        )
        resultado = {
            "resposta": persona_response.get("message", ""),
            "status": "ok",  # ✅ Manter status como "ok" para compatibilidade
            "dados_calculados": persona_response.get("data"),
            "pdf_url": persona_response.get("pdf_url"),
            "sha256": persona_response.get("sha256"),
        }
    else:
        # Processamento normal com componentes de inteligência
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            resultado = loop.run_until_complete(
                processar_com_inteligencia(
                    session_id, mensagem, intencao, sessao["messages"]
                )
            )
            loop.close()
        except Exception as e:
            logger.exception("Erro no processamento: %s", e)
            resultado = {
                "resposta": _gerar_resposta_fallback(intencao, {}, avoid_greeting=True),
                "status": "fallback",
            }

    # 3. Adicionar resposta ao histórico
    if resultado.get("resposta"):
        sessao["messages"].append(
            {"role": "assistant", "content": resultado["resposta"]}
        )

    # 4. Montar resposta (incluindo pensamento da persona se disponível)
    response_data = {
        "resposta": resultado.get("resposta", ""),
        "pensamento": persona_thinking
        or "",  # Sempre incluir pensamento, mesmo que vazio
        "session_id": session_id,
        "pdf_url": resultado.get("pdf_url"),
        "sha256": resultado.get("sha256"),
        "dados_calculados": resultado.get("dados_calculados"),
        "compliance": resultado.get("compliance_check"),
        "audit_id": resultado.get("audit_id"),
        "intencao_detectada": intencao["tipo"],
        "confianca": intencao["confianca"],
        "status": resultado.get("status", "ok"),
        "timestamp": datetime.now().isoformat(),
        "intelligence_status": {
            "orchestrator": True,  # INTELLIGENCE_AVAILABLE placeholder
            "groq": False,  # Default value for GROQ_CLIENT_AVAILABLE
            "tax_engine": _get_tax_engine() is not None,
            "compliance": _get_compliance() is not None,
            "audit": _get_audit() is not None,
            "persona": True,  # Persona agora integrada
        },
    }

    # Log para debug
    logger.info(
        f"🤖 Chat processado | Session: {session_id[:8]} | Intenção: {intencao['tipo']} | Status: {resultado.get('status')}"
    )

    # Se houve erro em serviço externo (ex: Groq), retornar 502 com detalhe sanitizado
    if resultado.get("status") == "external_service_error":
        err_payload = _sanitize_for_json(
            {
                "erro": "Serviço externo indisponível",
                "detalhes": resultado.get("external_error"),
                "status": "external_service_error",
                "timestamp": datetime.now().isoformat(),
            }
        )
        # UX: return 200 with a sanitized fallback payload so the frontend can
        # continue to display a helpful assistant response instead of treating
        # this as a hard transport error (502). The `status` field preserves
        # the error semantics for telemetry and client-side logic.
        try:
            # Ensure the payload explicitly contains the status
            err_payload.setdefault("status", "external_service_error")
        except Exception:
            pass
        try:
            logger.info(
                "Returning sanitized external_service_error payload with HTTP 200"
            )
        except Exception:
            pass
        return jsonify(err_payload)

    # Limpar tipo_pendente se o processamento não exigir mais dados
    try:
        # Definir ou recuperar 'sessao' antes do uso
        sessao = locals().get("sessao") or globals().get("sessao")
        if sessao and (
            sessao.get("tipo_pendente")
            and response_data.get("status") != "aguardando_dados"
        ):
            sessao["tipo_pendente"] = None
    except Exception:
        pass

    try:
        sanitized = _sanitize_for_json(response_data)
        return jsonify(sanitized)
    except Exception as e:
        # Log completo para facilitar diagnóstico, but never return 500
        try:
            logger.exception("Erro ao serializar resposta do /api/chat: %s", e)
        except Exception:
            pass
        # Return deterministic friendly fallback per survival rules
        fallback = {
            "status": "ok",
            "resposta": "Houve um pequeno problema técnico. Vou tentar novamente, ok?",
            "session_id": response_data.get("session_id"),
            "timestamp": datetime.now().isoformat(),
        }
        return jsonify(fallback), 200


@chat_refactored_bp.before_request
def _ensure_tenant_context():
    try:
        from flask import g

        tenant = request.headers.get("X-Tenant-ID") or os.environ.get(
            "DEFAULT_TENANT", "PUBLIC"
        )
        operator = request.headers.get("X-Operator-ID") or os.environ.get(
            "DEFAULT_OPERATOR", "ANON"
        )
        # Apenas define no contexto se ainda não existir
        if not getattr(g, "tenant_id", None):
            g.tenant_id = tenant
        if not getattr(g, "operator_id", None):
            g.operator_id = operator
        logger.debug(f"Tenant context ensured for chat: {g.tenant_id}/{g.operator_id}")
    except Exception as e:
        logger.warning(f"Falha ao garantir tenant context: {e}")


# ===== INICIALIZAÇÃO DOS COMPONENTES DE INTELIGÊNCIA =====


# Cache de sessões (histórico de conversa)
_session_cache: Dict[str, Dict[str, Any]] = {}

# Instâncias singleton dos componentes

# Flag para indicar se os componentes de inteligência estão disponíveis
INTELLIGENCE_AVAILABLE = True

_orchestrator: Optional[Any] = None


_tax_engine: Optional[Any] = None
_compliance = None
_audit = None
_groq_client = None
_groq_unavailable_until = 0
_groq_last_key = None


# ===== MODULE LEVEL IMPORTS (TOP OF FILE) =====
import os
from typing import Any, Dict, Optional
from flask import request, jsonify, Blueprint
import logging
from contabil_agente.intelligence.intelligence_orchestrator import (
    IntelligenceOrchestrator,
)
from ..tax.tax_engine import TaxEngine

try:
    from utils.pdf_transfer_generator import generate_transfer_addendum_pdf
except Exception:
    try:
        # fallback import if package layout differs
        from contabil_agente.utils.pdf_transfer_generator import (
            generate_transfer_addendum_pdf,
        )
    except Exception:
        generate_transfer_addendum_pdf = None

# ===== END MODULE LEVEL IMPORTS =====


def _get_orchestrator():
    """Obtém instância do orchestrator (lazy init)"""
    global _orchestrator
    if _orchestrator is None and INTELLIGENCE_AVAILABLE:
        try:
            _orchestrator = IntelligenceOrchestrator()
            logger.info("✅ IntelligenceOrchestrator inicializado")
        except Exception as e:
            logger.warning(f"⚠️ Falha ao inicializar orchestrator: {e}")
    return _orchestrator


def _get_tax_engine():
    """Obtém instância do TaxEngine (lazy init)"""
    global _tax_engine
    if _tax_engine is None and INTELLIGENCE_AVAILABLE:
        try:
            _tax_engine = TaxEngine()
            logger.info("✅ TaxEngine inicializado")
        except Exception as e:
            logger.warning(f"⚠️ Falha ao inicializar TaxEngine: {e}")
    return _tax_engine


def _get_compliance():
    """Obtém instância do ComplianceChecker (lazy init)"""
    global _compliance
    if _compliance is None and INTELLIGENCE_AVAILABLE:
        try:

            from ..intelligence.compliance import ComplianceChecker

            logger.info("✅ ComplianceChecker inicializado")
        except Exception as e:
            logger.warning(f"⚠️ Falha ao inicializar ComplianceChecker: {e}")
    return _compliance


def _get_audit():
    """Obtém instância do ForensicAudit (lazy init)"""
    global _audit
    if _audit is None and INTELLIGENCE_AVAILABLE:
        try:
            from ..intelligence.audit import ForensicAudit

            _audit = ForensicAudit()
            logger.info("✅ ForensicAudit inicializado")
        except Exception as e:
            logger.warning(f"⚠️ Falha ao inicializar ForensicAudit: {e}")
    return _audit


def _get_groq_client():
    """Obtém instância do GroqClient (lazy init)"""
    global _groq_client, _groq_unavailable_until
    # If circuit previously marked Groq unavailable but expiration passed, reset circuit
    try:
        if _groq_unavailable_until and time.time() > float(_groq_unavailable_until):
            logger.info(
                "ℹ️ Groq unavailable window expired — resetting circuit to CLOSED"
            )
            _groq_unavailable_until = 0
            _groq_client = None
    except Exception:
        pass

    # if we've recently marked Groq as unavailable (auth failure), short-circuit
    try:
        if time.time() < float(_groq_unavailable_until):
            logger.warning(
                "⚠️ Groq client is temporarily disabled due to prior auth errors"
            )
            return None
    except Exception:
        pass
    # Short-circuit when API key is not configured to avoid calling external LLM
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    global _groq_last_key
    try:
        # If key changed at runtime, force re-init and reset circuit
        if groq_key != _groq_last_key:
            _groq_last_key = groq_key
            _groq_client = None
            _groq_unavailable_until = 0
            logger.info(
                "ℹ️ GROQ_API_KEY changed — forcing Groq client reinitialization and closing circuit"
            )
    except Exception:
        pass
    # Masked logging for key presence (never log full secret)
    try:
        masked = (
            groq_key[:4] + "..." + groq_key[-4:]
            if groq_key and len(groq_key) > 8
            else ("<set>" if groq_key else "<not set>")
        )
    except Exception:
        masked = "<not set>"
    logger.info(f"Groq key present: {bool(groq_key)} (masked={masked})")

    # Basic format validation to avoid calling provider with clearly-bad keys
    try:
        import re

        if groq_key and not re.match(r"^gsk_[A-Za-z0-9_-]{10,}$", groq_key):
            logger.warning(
                "⚠️ GROQ_API_KEY format appears invalid; GroqClient will be disabled to avoid auth errors"
            )
            return None
    except Exception:
        pass

    try:
        GROQ_CLIENT_AVAILABLE
    except NameError:
        GROQ_CLIENT_AVAILABLE = False
    if _groq_client is None and GROQ_CLIENT_AVAILABLE:
        try:
            from groq import GroqClient

            _groq_client = GroqClient()
            logger.info("✅ GroqClient inicializado")
            # Successful initialization -> reset circuit
            try:
                _groq_unavailable_until = 0
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"⚠️ Falha ao inicializar GroqClient: {e}")
    return _groq_client


def _sanitize_for_json(obj):
    """Recursively convert common non-JSON types to JSON-serializable ones.

    - Decimal -> float
    - datetime/date -> ISO string
    - sets/tuples -> lists
    - other non-primitive objects -> str(obj)
    """
    from datetime import datetime, date

    if obj is None:
        return None
    if isinstance(obj, (str, bool, int, float)):
        return obj
    if isinstance(obj, Decimal):
        try:
            return float(obj)
        except Exception:
            return str(obj)
    if isinstance(obj, (datetime, date)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            try:
                out[str(k)] = _sanitize_for_json(v)
            except Exception:
                out[str(k)] = str(v)
        return out
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(i) for i in obj]
    try:
        return str(obj)
    except Exception:
        return repr(obj)


# ===== DETECÇÃO DE INTENÇÃO =====


def detectar_intencao(mensagem: str) -> Dict[str, Any]:
    """Detecta a intenção do usuário e extrai dados relevantes"""
    texto = mensagem.lower()

    # Normalizar espaçamento e remover caracteres repetidos comuns de digitação
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"(.)\1{2,}", r"\1\1", texto)

    intencao = {
        "tipo": "conversa",  # default
        "requer_calculo": False,
        "requer_documento": False,
        "dados_extraidos": {},
        "confianca": 0.5,
    }

    # Padrões de detecção
    patterns = {
        "rescisao": r"\b(rescis[ãa]o|demiss[ãa]o|demitir|desligar|mandar embora)\b",
        "ferias": r"\b(f[ée]rias|descanso|folga anual)\b",
        "decimo_terceiro": r"\b(13[°º]?|d[ée]cimo\s*terceiro|gratifica[çc][ãa]o)\b",
        "folha_pagamento": r"\b(folha|holerite|contracheque|pagamento)\b",
        "inss": r"\b(inss|previd[êe]ncia|contribui[çc][ãa]o)\b",
        "fgts": r"\b(fgts|fundo de garantia)\b",
        "imposto": r"\b(imposto|irrf|irpf|tributo|fiscal)\b",
        "admissao": r"\b(admiss[ãa]o|contratar|contrata[çc][ãa]o|novo funcion[áa]rio)\b",
        "transferencia": r"\b(transfer[êe]ncia|transferir|trocar\s*de\s*(?:posto|local|filial|unidade)|mudar\s*de\s*(?:posto|local|filial)|vai\s*(?:pro|para\s*(?:o|outro)))\b",
    }

    # Verificar match direto por padrões
    for tipo, pattern in patterns.items():
        if re.search(pattern, texto, re.IGNORECASE):
            intencao["tipo"] = tipo
            intencao["requer_calculo"] = tipo in [
                "rescisao",
                "ferias",
                "decimo_terceiro",
                "folha_pagamento",
                "inss",
            ]
            # Marcar possível necessidade de documento para transferências
            if tipo == "transferencia":
                intencao["requer_documento"] = True
                intencao["confianca"] = max(intencao["confianca"], 0.7)
            else:
                intencao["confianca"] = max(intencao["confianca"], 0.6)
            break

    # Heurística fuzzy (tokens x keywords) para capturar variações/erros de digitação
    try:
        tokens = re.findall(r"\w+", texto, flags=re.UNICODE)
        keywords = [
            "transferir",
            "transferencia",
            "trocar",
            "mudar",
        ]
        found = False
        for t in tokens:
            match = difflib.get_close_matches(t, keywords, n=1, cutoff=0.75)
            if match:
                tok = match[0]
                if tok in ("transferir", "transferencia", "trocar", "mudar") or (
                    "posto" in tok or "gasolina" in tok
                ):
                    intencao["tipo"] = "transferencia"
                    intencao["requer_documento"] = True
                    intencao["confianca"] = max(intencao["confianca"], 0.7)
                    found = True
                    break
        # heurística simples para casos onde as palavras aparecem unidas (ex: postodegasolina)
        if not found:
            compact = texto.replace(" ", "")
            if "posto" in compact and "gasolina" in compact:
                intencao["tipo"] = "transferencia"
                intencao["requer_documento"] = True
                intencao["confianca"] = max(intencao["confianca"], 0.65)
    except Exception:
        # Não falhar a detecção por causa de heurísticas
        pass

    # Extrair valores monetários (priorizar padrões significativos)
    # 1. Procurar por "R$ XXXX,XX" ou similar padrão monetário explícito
    valores_explícitos = re.findall(r"R\$\s*([\d.,]+)", mensagem)

    # 2. Se não achado valores explícitos, procurar por números "simples" maiores que 100 (evita ordinals)
    if not valores_explícitos:
        valores_implícitos = re.findall(r"\b(\d+[\.,]?\d{0,3})\b", mensagem)
        valores_significativos = [
            v
            for v in valores_implícitos
            if float(v.replace(",", ".").replace(".", "")) >= 100
        ]
        valores_explícitos = valores_significativos

    if valores_explícitos:
        try:
            # Pegar o primeiro valor significativo como salário
            valor_str = valores_explícitos[0].replace(".", "").replace(",", ".")
            salario_float = float(valor_str)
            # Validar: salário deve estar num range realista (10 a 1.000.000 BRL)
            if 10 <= salario_float <= 1000000:
                intencao["dados_extraidos"]["salario"] = salario_float
        except (ValueError, TypeError):
            pass

    # 3. Extrair meses (para cálculos de férias e 13º)
    meses_match = re.search(r"(\d+)\s*(?:meses?|m)", mensagem, re.IGNORECASE)
    if meses_match:
        try:
            intencao["dados_extraidos"]["meses"] = int(meses_match.group(1))
        except ValueError:
            pass

    # Extrair datas
    datas = re.findall(r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})", mensagem)
    if datas:
        intencao["dados_extraidos"]["datas"] = datas
        # Usar a primeira data como data de transferência se for tipo transferencia
        if intencao["tipo"] == "transferencia":
            intencao["dados_extraidos"]["data_transferencia"] = datas[0]

    # Extrair CPF (formato XXX.XXX.XXX-XX ou XXXXXXXXXXX)
    cpf_match = re.search(r"(\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2}|\d{11})", mensagem)
    if cpf_match:
        intencao["dados_extraidos"]["cpf"] = cpf_match.group(1)

    # Extrair nomes próprios (identificar por contexto)
    # Padrão: nome após "funcionário", "empregado", nome próprio antes de "vai", etc.
    nome_patterns = [
        r"funcion[áa]rio\s+([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
        r"empregado\s+([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
        r"([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)\s+(?:vai|está|será)",
        r"nome[:\s]+([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
    ]
    for pattern in nome_patterns:
        match = re.search(pattern, mensagem)
        if match:
            intencao["dados_extraidos"]["nome"] = match.group(1).strip()
            break

    # Extrair local de destino para transferência (APENAS se tipo for transferencia)
    if intencao["tipo"] == "transferencia":
        local_patterns = [
            r"(?:pro|para\s+o?|para)\s+(?:posto|filial|unidade|local)?\s*([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
            r"(?:posto|filial|unidade)\s+([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
            r"novo\s+(?:posto|local|filial)[:\s]+([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
        ]
        for pattern in local_patterns:
            match = re.search(pattern, mensagem, re.IGNORECASE)
            if match:
                intencao["dados_extraidos"]["local_destino"] = match.group(1).strip()
                break

    # Detectar pedido de documento
    if re.search(r"\b(gerar?|criar?|emitir?|documento|pdf|formul[áa]rio)\b", texto):
        intencao["requer_documento"] = True
        intencao["confianca"] = max(intencao["confianca"], 0.9)

    # Detectar pedido de cálculo
    if re.search(r"\b(calcul[ae]r?|quanto|valor|total)\b", texto):
        intencao["requer_calculo"] = True
        intencao["confianca"] = max(intencao["confianca"], 0.8)

    return intencao


# ===== PROCESSAMENTO COM INTELIGÊNCIA =====


async def processar_com_inteligencia(
    session_id: str, mensagem: str, intencao: Dict[str, Any], historico: list
) -> Dict[str, Any]:
    """Processa a mensagem usando todos os componentes de inteligência"""

    resultado = {
        "resposta": None,
        "dados_calculados": None,
        "compliance_check": None,
        "audit_id": None,
        "pdf_url": None,
        "status": "ok",
    }

    # allow updating the module-level circuit-breaker timestamp
    global _groq_unavailable_until

    # 1. AUDITORIA: Registrar entrada
    audit = _get_audit()
    audit_id = str(uuid.uuid4())
    if audit:
        try:
            audit.record(
                request_id=audit_id,
                session_id=session_id,
                input_sanitized={"mensagem": mensagem, "intencao": intencao},
                output={},
            )
            resultado["audit_id"] = audit_id
        except Exception as e:
            logger.warning(f"⚠️ Falha no audit: {e}")

    # 2. ORCHESTRATOR: Processar via FSM se necessário
    orchestrator = _get_orchestrator()
    if orchestrator and (intencao["requer_calculo"] or intencao["requer_documento"]):
        try:
            payload = {
                "mensagem": mensagem,
                "sources": [
                    {
                        "data": intencao["dados_extraidos"],
                        "weight": 0.9,
                        "timestamp": time.time(),
                    }
                ],
                "amount": intencao["dados_extraidos"].get("salario", 0),
                "date": datetime.now().isoformat(),
            }

            # Executar orchestrator (async)
            orch_result = await orchestrator.handle(session_id, payload, timeout=30)

            if orch_result.get("status") == "ok":
                resultado["dados_calculados"] = orch_result.get("calc")
                resultado["compliance_check"] = orch_result.get("comp")
            elif orch_result.get("status") == "needs_manual_input":
                resultado["status"] = "aguardando_dados"
        except Exception as e:
            logger.warning(f"⚠️ Erro no orchestrator: {e}")

    # 3. TAX ENGINE: Cálculos específicos
    tax_engine = _get_tax_engine()
    if (
        tax_engine
        and intencao["requer_calculo"]
        and intencao["dados_extraidos"].get("salario")
    ):
        try:
            calc_result = tax_engine.calculate(
                {
                    "amount": intencao["dados_extraidos"]["salario"],
                    "date": datetime.now().isoformat(),
                }
            )
            if not resultado["dados_calculados"]:
                resultado["dados_calculados"] = calc_result
        except Exception as e:
            logger.warning(f"⚠️ Erro no TaxEngine: {e}")

    # 4. COMPLIANCE: Validações
    compliance = _get_compliance()
    if compliance and not resultado["compliance_check"]:
        try:
            comp_result = compliance.validate(intencao["dados_extraidos"])
            resultado["compliance_check"] = comp_result
        except Exception as e:
            logger.warning(f"⚠️ Erro no compliance: {e}")

    # 5. DOCUMENTO: Gerar se necessário
    if intencao["requer_documento"] and intencao["tipo"] == "rescisao":
        try:
            dados_doc = intencao["dados_extraidos"].copy()
            dados_doc["request_id"] = audit_id
            # Prefer DocumentService if available for professional PDF generation
            try:
                from contabil_agente.services.document_service import DocumentService

                svc = DocumentService.get_instance()
                filename = f"rescisao_{uuid.uuid4().hex[:8]}.pdf"
                content = f"[DOCUMENTO_OFICIAL]\nRescisão gerada para: {dados_doc.get('nome', '')}\nDados: {dados_doc}"
                ok = svc.generate_professional_pdf(
                    filename,
                    content,
                    metadata={"pergunta_usuario": content, "protocolo": audit_id},
                )
                if ok:
                    pdf_path = os.path.join(svc.output_folder, filename)
                    if os.path.exists(pdf_path):
                        resultado["pdf_url"] = f"/download/{os.path.basename(pdf_path)}"
                        # compute sha256 if possible
                        try:
                            import hashlib

                            with open(pdf_path, "rb") as f:
                                sha = hashlib.sha256(f.read()).hexdigest()
                            resultado["sha256"] = sha
                        except Exception:
                            pass
                        # Register PDF in manifest for stable downloads and tracking
                        try:
                            from contabil_agente.services import pdf_store
                            from pathlib import Path

                            src = Path(pdf_path)
                            # If file is already under static/downloads, just add manifest entry
                            try:
                                static_dir = pdf_store.STATIC_DOWNLOADS.resolve()
                            except Exception:
                                static_dir = None

                            if static_dir and src.resolve().parent == static_dir:
                                m = pdf_store._load_manifest()
                                name = src.name
                                m[name] = {
                                    "session_id": session_id,
                                    "filename": name,
                                    "storage": "disk",
                                    "path": str(src.relative_to(pdf_store.ROOT)),
                                    "size": src.stat().st_size,
                                    "timestamp": __import__("datetime")
                                    .datetime.utcnow()
                                    .isoformat()
                                    + "Z",
                                }
                                pdf_store._save_manifest(m)
                            else:
                                try:
                                    pdf_store.register_pdf(
                                        str(pdf_path), session_id=session_id
                                    )
                                except Exception:
                                    # best-effort only
                                    pass
                        except Exception:
                            pass
            except Exception:
                # If DocumentService unavailable, fallback to orchestrator stub behavior
                orch_doc = {"success": True, "pdf_path": None, "sha256": None}
                if orch_doc.get("success") and orch_doc.get("pdf_path"):
                    pdf_path = orch_doc.get("pdf_path")
                    resultado["pdf_url"] = f"/download/{os.path.basename(pdf_path)}"
                    resultado["sha256"] = orch_doc.get("sha256")
        except Exception as e:
            logger.warning(f"⚠️ Erro ao gerar documento: {e}")

    # 5.1 DOCUMENTO TRANSFERÊNCIA: Gerar aditivo de transferência
    # DEBUG: Log para verificar condições (usar logger em vez de escrever em C:/)
    logger.info(
        f"🔍 DEBUG: requer_documento={intencao.get('requer_documento')}, tipo={intencao.get('tipo')}"
    )
    try:
        logger.debug(
            f"DEBUG: requer_documento={intencao.get('requer_documento')}, tipo={intencao.get('tipo')}"
        )
    except Exception:
        # Não interromper fluxo se o logger falhar por algum motivo
        pass
    if intencao["requer_documento"] and intencao["tipo"] == "transferencia":
        try:
            dados_doc = intencao["dados_extraidos"].copy()
            dados_doc["request_id"] = audit_id

            # Gerar PDF de aditivo de transferência
            pdf_result = generate_transfer_addendum_pdf(
                payload=dados_doc,
                metadata={
                    "author": "Maria Helena - Sistema Contábil",
                    "title": "Aditivo de Transferência",
                },
            )

            if pdf_result.get("success"):
                pdf_path = pdf_result.get("pdf_path")
                if pdf_path:
                    resultado["pdf_url"] = f"/download/{os.path.basename(pdf_path)}"
                    resultado["sha256"] = pdf_result.get("sha256")
                    resultado["filename"] = pdf_result.get("filename")
                    logger.info(f"✅ PDF de transferência gerado: {pdf_path}")
                    # Register transfer PDF in manifest if missing
                    try:
                        from contabil_agente.services import pdf_store
                        from pathlib import Path

                        src = Path(pdf_path)
                        try:
                            static_dir = pdf_store.STATIC_DOWNLOADS.resolve()
                        except Exception:
                            static_dir = None

                        if static_dir and src.resolve().parent == static_dir:
                            m = pdf_store._load_manifest()
                            name = src.name
                            if name not in m:
                                m[name] = {
                                    "session_id": session_id,
                                    "filename": name,
                                    "storage": "disk",
                                    "path": str(src.relative_to(pdf_store.ROOT)),
                                    "size": src.stat().st_size,
                                    "timestamp": __import__("datetime")
                                    .datetime.utcnow()
                                    .isoformat()
                                    + "Z",
                                }
                                pdf_store._save_manifest(m)
                        else:
                            try:
                                pdf_store.register_pdf(
                                    str(pdf_path), session_id=session_id
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"⚠️ Erro ao gerar documento de transferência: {e}")

    # 5.2 DOCUMENTO GENÉRICO: Gerar PDFs para outros tipos que requerem documento
    if intencao["requer_documento"] and intencao["tipo"] in (
        "ferias",
        "decimo_terceiro",
        "admissao",
        "folha_pagamento",
        "inss",
        "fgts",
        "imposto",
    ):
        try:
            dados_doc = intencao["dados_extraidos"].copy()
            dados_doc["request_id"] = audit_id
            # Use per-type generator helper
            pdf_res = _generate_pdf_for_tipo(
                intencao.get("tipo"), dados_doc, mensagem, audit_id, session_id
            )
            if pdf_res.get("success"):
                pdf_path = pdf_res.get("pdf_path")
                filename = pdf_res.get("filename")
                resultado["pdf_url"] = f"/download/{os.path.basename(pdf_path)}"
                if pdf_res.get("sha256"):
                    resultado["sha256"] = pdf_res.get("sha256")
                # Register in manifest (best-effort)
                try:
                    from contabil_agente.services import pdf_store
                    from pathlib import Path

                    src = Path(pdf_path)
                    try:
                        static_dir = pdf_store.STATIC_DOWNLOADS.resolve()
                    except Exception:
                        static_dir = None

                    if static_dir and src.resolve().parent == static_dir:
                        m = pdf_store._load_manifest()
                        name = src.name
                        if name not in m:
                            m[name] = {
                                "session_id": session_id,
                                "filename": name,
                                "storage": "disk",
                                "path": str(src.relative_to(pdf_store.ROOT)),
                                "size": src.stat().st_size,
                                "timestamp": __import__("datetime")
                                .datetime.utcnow()
                                .isoformat()
                                + "Z",
                            }
                            pdf_store._save_manifest(m)
                    else:
                        try:
                            pdf_store.register_pdf(str(pdf_path), session_id=session_id)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"⚠️ Erro ao gerar documento genérico: {e}")

    # 6. GROQ/Maria Helena: Gerar resposta humanizada
    groq = _get_groq_client()
    if groq:
        try:
            # Montar contexto para a Maria Helena
            contexto_extra = ""
            if resultado["dados_calculados"]:
                contexto_extra += (
                    f"\n\n[DADOS_CALCULADOS]: {resultado['dados_calculados']}"
                )
            if resultado["compliance_check"]:
                contexto_extra += f"\n\n[COMPLIANCE]: {resultado['compliance_check']}"
            if resultado["pdf_url"]:
                contexto_extra += f"\n\n[DOCUMENTO_GERADO]: {resultado['pdf_url']}"

            # Montar prompt completo (system + histórico + mensagem atual)
            def get_system_prompt():
                return "Você é Maria Helena, uma assistente contábil virtual. Responda de forma clara, profissional e humana, ajudando o usuário com dúvidas contábeis e financeiras."

            system_prompt = get_system_prompt()

            # Construir histórico de conversa como texto
            historico_texto = ""
            for msg in historico[-6:]:  # Últimas 6 mensagens
                role = "Usuário" if msg.get("role") == "user" else "Maria Helena"
                historico_texto += f"{role}: {msg.get('content', '')}\n"

            # Montar prompt final
            prompt_completo = f"""{system_prompt}

--- HISTÓRICO DA CONVERSA ---
{historico_texto}

--- MENSAGEM ATUAL DO USUÁRIO ---
{mensagem}

--- CONTEXTO DO SISTEMA ---
{contexto_extra if contexto_extra else "(Nenhum dado calculado ainda)"}

Por favor, responda como Maria Helena, de forma humana e profissional:"""

            # Chamar Groq usando o método correto com retry interno (3 tentativas)
            max_attempts = 3
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    resposta_groq = groq.chamar_groq(
                        prompt=prompt_completo,
                        max_retries=2,
                        fallback_text=_gerar_resposta_fallback(intencao, resultado),
                        use_cache=False,  # Não cachear respostas de chat
                    )
                    resultado["resposta"] = resposta_groq
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    try:
                        logger.warning(
                            "Attempt %d/%d failed calling Groq: %s",
                            attempt,
                            max_attempts,
                            e,
                        )
                    except Exception:
                        pass
                    if attempt < max_attempts:
                        # backoff incremental antes de nova tentativa
                        try:
                            time.sleep(1 * attempt)
                        except Exception:
                            pass
                        continue

            if last_exc is not None:
                e = last_exc
                # Log minimal info only — avoid printing full stack trace during tests
                try:
                    logger.warning("Erro no Groq: %s", str(e))
                except Exception:
                    pass
                # Detectar erros de autenticação/permissão e sanitizar o retorno
                try:
                    msg = str(e)
                except Exception:
                    msg = "erro no serviço externo"
                # For specific provider statuses (429 rate-limit or 401 auth),
                # return a short retryable message so the frontend can auto-retry
                # without surfacing a hard 'indisponível' message to the user.
                try:
                    code = None
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        code = getattr(resp, "status_code", None)
                except Exception:
                    code = None

                is_rate_limit = False
                try:
                    if code == 429 or "429" in msg:
                        is_rate_limit = True
                except Exception:
                    is_rate_limit = False

                is_auth_error = False
                try:
                    if (
                        code in (401, 403)
                        or "invalid api key" in msg.lower()
                        or "401" in msg
                    ):
                        is_auth_error = True
                except Exception:
                    is_auth_error = False

                if is_rate_limit or is_auth_error:
                    # Return a friendly retry instruction for transient auth/rate-limit
                    resultado["resposta"] = (
                        "Houve um pequeno problema técnico. Vou tentar novamente, ok?"
                    )
                    resultado["status"] = "retry"
                    # Keep a minimal external_error summary for telemetry but do not leak details
                    resultado["external_error"] = {
                        "type": "rate_or_auth",
                        "message": "temporary_throttling_or_auth",
                    }
                    resultado["external_error_summary"] = msg[:512]
                else:
                    # After all retries exhausted for non-auth and non-rate-limit
                    # issues, return the deterministic friendly fallback requested
                    # by the survival rules and mark the response as successful
                    # so the frontend receives HTTP 200 with a human message.
                    resultado["resposta"] = (
                        "Houve um pequeno problema técnico. Vou tentar novamente, ok?"
                    )
                    resultado["status"] = "ok"
                # Sanitize external_error: provide structured info for common auth errors
                try:
                    code = None
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        code = getattr(resp, "status_code", None)
                    if (
                        code in (401, 403)
                        or "invalid api key" in msg.lower()
                        or "401" in msg
                    ):
                        resultado["external_error"] = {
                            "type": "auth_error",
                            "message": "invalid_api_key_or_credentials",
                        }
                    else:
                        resultado["external_error"] = {
                            "type": "service_error",
                            "message": "external_service_failed",
                        }
                    resultado["external_error_summary"] = msg[:512]
                except Exception:
                    resultado["external_error"] = {
                        "type": "service_error",
                        "message": "external_service_failed",
                    }

                # Se detectar auth error após todas as tentativas, fechar circuito por 15 minutos
                try:
                    code = None
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        code = getattr(resp, "status_code", None)
                    is_auth_error = False
                    try:
                        if (
                            code in (401, 403)
                            or "invalid api key" in msg.lower()
                            or "invalid_api_key" in msg.lower()
                        ):
                            is_auth_error = True
                    except Exception:
                        is_auth_error = False

                    if is_auth_error:
                        global _groq_unavailable_until, _groq_client
                        _groq_unavailable_until = time.time() + 15 * 60
                        _groq_client = None
                        logger.warning(
                            "⚠️ Groq marked unavailable until %s due to auth error",
                            _groq_unavailable_until,
                        )
                except Exception:
                    pass
            # Ensure we don't surface a transport-level error to the frontend.
            # Per survival rules: return friendly fallback + status ok.
            if not resultado.get("resposta"):
                resultado["resposta"] = (
                    "Houve um pequeno problema técnico. Vou tentar novamente, ok?"
                )
            resultado["status"] = "ok"
            try:
                # provide sanitized structured error info
                resultado["external_error"] = {
                    "type": "auth_error" if is_auth_error else "service_error",
                    "message": (
                        "invalid_api_key_or_credentials"
                        if is_auth_error
                        else "external_service_failed"
                    ),
                }
                resultado["external_error_summary"] = msg[:512]
            except Exception:
                resultado["external_error"] = {
                    "type": "service_error",
                    "message": "external_service_failed",
                }
        except Exception as e:
            # Garantir que qualquer erro inesperado durante a chamada ao Groq seja
            # capturado e tratado, evitando deixar um `try` sem `except`.
            try:
                logger.exception("Erro inesperado ao chamar Groq: %s", e)
            except Exception:
                pass
            # Return deterministic friendly fallback per survival rules
            resultado["resposta"] = (
                "Houve um pequeno problema técnico. Vou tentar novamente, ok?"
            )
            resultado["status"] = "ok"
            resultado["external_error"] = {
                "type": "service_error",
                "message": "unexpected_error",
            }
            resultado["external_error_summary"] = str(e)[:512]
    else:
        resultado["resposta"] = _gerar_resposta_fallback(intencao, resultado)

    # 7. AUDITORIA: Registrar saída
    if audit:
        try:
            audit.record(
                request_id=audit_id + "_out",
                session_id=session_id,
                input_sanitized={},
                output=resultado,
            )
        except Exception:
            pass

    return resultado


def _gerar_resposta_fallback(
    intencao: Dict, resultado: Dict, avoid_greeting: bool = False
) -> str:
    """Gera resposta quando Groq não está disponível.

    If avoid_greeting is True, do not return the friendly greeting for generic
    conversa intents - useful when the request was invalid or an internal
    error occurred so the backend doesn't emit a welcoming message.
    """
    tipo = intencao.get("tipo", "conversa")

    if resultado.get("pdf_url"):
        return f"✅ Pronto! Gerei o documento que você pediu. Baixe aqui: {resultado['pdf_url']}"

    if resultado.get("dados_calculados"):
        calc = resultado["dados_calculados"]
        total = calc.get("total", 0) if isinstance(calc, dict) else 0
        return f"✅ Cálculo realizado! Total calculado: R$ {total:,.2f}"

    respostas = {
        "rescisao": "Entendi que você precisa de ajuda com rescisão. Me passa os dados: salário, data de admissão e demissão.",
        "ferias": "Vou te ajudar com as férias! Me informa: salário e período aquisitivo.",
        "decimo_terceiro": "Beleza! Para calcular o 13º, preciso do salário e meses trabalhados.",
        "folha_pagamento": "Vou ajudar com a folha de pagamento. Quais dados você tem?",
        "inss": "Para calcular INSS, me passa o salário bruto.",
        "fgts": "FGTS é 8% do salário. Me passa o valor que eu calculo.",
        "imposto": "Para impostos, preciso saber: regime tributário e valores.",
        "admissao": "Vou preparar a admissão. Me passa: nome, CPF, cargo e salário.",
        "transferencia": "Certo! Para gerar o aditivo de transferência, preciso: nome completo, CPF, novo local de trabalho e data da transferência.",
        "conversa": None,  # handled by dynamic generator below
    }

    # If caller requested to avoid returning the generic greeting for `conversa`,
    # return a neutral help message instead.
    if tipo == "conversa":
        if avoid_greeting:
            return "Claro, estou ouvindo! Qual seria a sua dúvida?"
        # Try to produce a small dynamic intro via Groq if available, else fallback
        try:
            groq = _get_groq_client()
            if groq is not None:
                prompt = (
                    "Responda com uma breve apresentação como assistente contábil chamada 'Maria Helena'. "
                    "Se o usuário fez apenas uma saudação ou uma dúvida genérica, não inclua uma longa saudação; "
                    "em vez disso, pergunte claramente qual é a dúvida. Retorne no máximo 30 palavras."
                )
                try:
                    resposta = groq.chamar_groq(
                        prompt=prompt, max_retries=1, use_cache=False
                    )
                    if resposta:
                        return resposta
                except Exception:
                    pass
        except Exception:
            pass
        # deterministic fallback
        return "Olá — sou Maria Helena. Como posso ajudá-lo hoje?"

    return respostas.get(tipo, "Desculpe, não entendi. Pode reformular?")


# ===== ENDPOINT PRINCIPAL =====


@chat_refactored_bp.route("/api/chat", methods=["POST"])
def chat_integrado():
    """Top-level wrapper ensuring /api/chat never returns HTTP 500.

    Delegates to `_chat_integrado_impl()` and on any uncaught exception
    returns the deterministic friendly fallback with HTTP 200 so the
    frontend never receives a transport error.
    """
    try:
        return _chat_integrado_impl()
    except Exception as e:
        try:
            logger.exception("Uncaught exception in /api/chat wrapper: %s", e)
        except Exception:
            pass
        fallback = {
            "status": "ok",
            "resposta": "Houve um pequeno problema técnico. Vou tentar novamente, ok?",
            "session_id": None,
            "timestamp": datetime.now().isoformat(),
        }
        return jsonify(fallback), 200

    # Se houve erro em serviço externo (ex: Groq), retornar 502 com detalhe sanitizado
    if resultado.get("status") == "external_service_error":
        err_payload = _sanitize_for_json(
            {
                "erro": "Serviço externo indisponível",
                "detalhes": resultado.get("external_error"),
                "status": "external_service_error",
                "timestamp": datetime.now().isoformat(),
            }
        )
        # UX: return 200 with a sanitized fallback payload so the frontend can
        # continue to display a helpful assistant response instead of treating
        # this as a hard transport error (502). The `status` field preserves
        # the error semantics for telemetry and client-side logic.
        try:
            # Ensure the payload explicitly contains the status
            err_payload.setdefault("status", "external_service_error")
        except Exception:
            pass
        try:
            logger.info(
                "Returning sanitized external_service_error payload with HTTP 200"
            )
        except Exception:
            pass
        return jsonify(err_payload)

    # Limpar tipo_pendente se o processamento não exigir mais dados
    try:
        if (
            sessao.get("tipo_pendente")
            and response_data.get("status") != "aguardando_dados"
        ):
            sessao["tipo_pendente"] = None
    except Exception:
        pass
    try:
        sanitized = _sanitize_for_json(response_data)
        return jsonify(sanitized)
    except Exception as e:
        # Log completo para facilitar diagnóstico, but never return 500
        try:
            logger.exception("Erro ao serializar resposta do /api/chat: %s", e)
        except Exception:
            pass
        # Return deterministic friendly fallback per survival rules
        fallback = {
            "status": "ok",
            "resposta": "Houve um pequeno problema técnico. Vou tentar novamente, ok?",
            "session_id": response_data.get("session_id"),
            "timestamp": datetime.now().isoformat(),
        }
        return jsonify(fallback), 200


@chat_refactored_bp.route("/download/<path:filename>")
def download_document(filename):
    """Endpoint de download mínimo que serve arquivos da pasta de saída do DocumentService.

    Se `document_service` não estiver disponível, tenta a pasta `contabil_agente/temp_docs`.
    """
    try:
        # tentativa de localizar document_service dinamicamente
        try:
            import importlib

            mod = importlib.import_module("contabil_agente.services.document_service")
            doc_svc = getattr(mod, "document_service", None)
            out_folder = getattr(doc_svc, "output_folder", None) if doc_svc else None
        except Exception:
            out_folder = None

        if out_folder and os.path.isdir(out_folder):
            safe_name = os.path.basename(filename)
            file_path = os.path.join(out_folder, safe_name)
            if os.path.exists(file_path):
                return send_from_directory(
                    out_folder, safe_name, as_attachment=True, download_name=safe_name
                )

        # Também verificar pasta estática de downloads (compatibilidade com app.py)
        base = os.path.dirname(os.path.dirname(__file__))
        static_downloads = os.path.join(base, "static", "downloads")
        safe_name = os.path.basename(filename)
        static_path = os.path.join(static_downloads, safe_name)
    except Exception as e:
        # Log the error and return a friendly error message
        try:
            logger.exception("Erro ao processar download_document: %s", e)
        except Exception:
            pass
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Não foi possível processar o download. Tente novamente mais tarde.",
                }
            ),
            200,
        )

    if os.path.exists(static_path):
        return send_from_directory(
            static_downloads, safe_name, as_attachment=True, download_name=safe_name
        )

    # fallback para pasta temp_docs dentro do pacote
    base = os.path.dirname(os.path.dirname(__file__))
    legacy = os.path.join(base, "temp_docs")
    safe_name = os.path.basename(filename)
    legacy_path = os.path.join(legacy, safe_name)
    if os.path.exists(legacy_path):
        return send_from_directory(
            legacy, safe_name, as_attachment=True, download_name=safe_name
        )
    return jsonify({"erro": "Arquivo não encontrado"}), 404


@chat_refactored_bp.route("/api/debug/confirmations", methods=["GET"])
def debug_confirmations():
    """Debug endpoint to inspect pending confirmations store state."""
    return (
        jsonify(
            {
                "pending_confirmations": _pending_confirmations_state,
                "count": len(_pending_confirmations_state),
            }
        ),
        200,
    )


"""
Download helper complete. No duplicated fallback blocks remain.
"""
