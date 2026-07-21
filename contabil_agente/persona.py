"""Persona utilities (Maria Helena) moved out of agent_contabil.py

This module exposes the `SYSTEM_PROMPT_MARIA_HELENA` constant and the
`process_intelligence_request_persona` function. It accesses runtime
state from `contabil_agente.agent_contabil` lazily to avoid circular imports.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from contabil_agente.utils import (
    parse_brl_to_float,
    format_brl,
    _is_approximate_text,
    _normalize_k_suffix,
    _is_small_talk,
)

try:
    from contabil_agente.utils import send_audit
except Exception:
    send_audit = None

logger = logging.getLogger("contabil_agente.persona")

SYSTEM_PROMPT_MARIA_HELENA = """
Maria Helena - Auditoria Sênior

Regras:
1) Especialidade: Responda apenas com conhecimento técnico tributário e contábil. Seja preciso.
2) Proibição de Chute: Nunca invente valores ou regras; se desconhecido, peça confirmação ou dados oficiais.
3) Rastreabilidade: Todas as decisões devem ser registradas com `request_id` e `session_id`.
4) Confirmação: Solicite confirmação explícita quando valores forem informados manualmente.
5) Formatação BRL: Sempre apresente valores em formato BRL `R$ 1.234,56`.
6) Ambiguidade: Quando múltiplas fontes conflitarem, explique precedência e escolha baseada em peso/tempo.
7) Memória SQLite: Use cache local para memória de sessão, registre histórico de alterações.
8) Decisão Executiva: Dê uma única recomendação executiva clara (sim/não, valor númerico) quando possível.
9) Tom de Auditoria: Seja breve, sem emojis, registre logs de auditoria para cada passo.
"""


def _get_runtime_refs() -> tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """Lazily obtain runtime references from agent_contabil to avoid circular imports.

    Returns (_intelligence, _audit_logger, process_intelligence_request_or_none)
    """
    try:
        ag = importlib.import_module("contabil_agente.agent_contabil")
        _intelligence = getattr(ag, "_intelligence", None)
        _audit_logger = getattr(ag, "_audit_logger", None)
        process_fn = getattr(ag, "process_intelligence_request", None)
        return _intelligence, _audit_logger, process_fn
    except Exception:
        return None, None, None


def _extrair_cpf_texto(texto: str) -> Optional[str]:
    if not texto:
        return None
    match = re.search(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b", texto)
    if not match:
        return None
    cpf = re.sub(r"\D", "", match.group(1))
    return cpf if len(cpf) == 11 else None


def _eh_solicitacao_extrato_fgts(texto: str) -> bool:
    if not texto:
        return False
    texto_norm = texto.lower().strip()
    padroes = [
        r"\bmeu\s+extrato\s+do\s+fgts\b",
        r"\bextrato\s+fgts\b",
        r"\bbuscar\s+extrato\s+fgts\b",
        r"\bconsultar\s+fgts\b",
        r"\bconsultar\s+extrato\s+fgts\b",
        r"\bextrato\s+de\s+fgts\b",
        r"\bfgts\s+extrato\b",
    ]
    return any(re.search(padrao, texto_norm) for padrao in padroes)


def _executar_extrato_fgts_real(
    session_id: str, cpf: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        from pathlib import Path

        from contabil_agente.tools.sovereign_rpa_worker import SovereignRPAWorker
    except Exception as exc:
        return {
            "status": "ok",
            "message": (
                "Não consegui acionar o worker real do FGTS porque a integração "
                f"não está disponível neste ambiente: {exc}"
            ),
        }

    work_root = Path(tempfile.mkdtemp(prefix="fgts_worker_"))
    repo_root = Path(__file__).resolve().parents[2]
    profile_root = Path.home() / ".sovereign_rpa_caixa"
    default_profile_dir = os.getenv("FGTS_BROWSER_PROFILE_DIRECTORY", "Default")
    default_user_data_dir = os.getenv("FGTS_BROWSER_USER_DATA_DIR") or str(
        profile_root / default_profile_dir
    )
    default_buster_dir = (
        os.getenv("FGTS_BUSTER_EXTENSION_DIR")
        or os.getenv("SOVEREIGN_BUSTER_EXTENSION_DIR")
        or (
            str(repo_root / "extensions" / "buster")
            if (repo_root / "extensions" / "buster").exists()
            else None
        )
        or (
            str(repo_root / "extensions" / "buster.crx")
            if (repo_root / "extensions" / "buster.crx").exists()
            else None
        )
    )
    config = {
        "fgts_url": os.getenv("FGTS_CAIXA_URL") or "https://www.caixa.gov.br",
        "buster_extension_dir": default_buster_dir,
        "user_data_dir": default_user_data_dir,
        "profile_directory": default_profile_dir,
        "download_dir": str(work_root / "downloads"),
        "payload_source": payload.get("message") or payload.get("user_text") or "",
    }

    worker = SovereignRPAWorker(
        f"{session_id}-fgts",
        work_root,
        config,
        dry_run=False,
    )

    try:
        with worker:
            resultado = worker.executar("extrato_fgts", {"cpf": cpf})
    except Exception as exc:
        logger.warning("Falha ao executar extrato FGTS real: %s", exc, exc_info=True)
        return {
            "status": "ok",
            "message": (
                "Não consegui concluir a consulta real do extrato FGTS agora. "
                f"Motivo: {exc}"
            ),
        }

    if resultado.get("status") == "success":
        pdf_url = resultado.get("pdf_url") or resultado.get("path") or ""
        mensagem = "Consulta FGTS oficial concluída."
        if pdf_url:
            mensagem = f"{mensagem} PDF disponível em: {pdf_url}"
        resposta = {
            "status": "ok",
            "message": mensagem,
            "data": resultado,
            "pdf_url": resultado.get("pdf_url"),
            "sha256": resultado.get("sha256"),
        }
        try:
            if send_audit is not None:
                send_audit(
                    "persona.fgts_extrato.success",
                    level="info",
                    context={
                        "session_id": session_id,
                        "cpf": cpf,
                        "pdf_url": resultado.get("pdf_url"),
                    },
                )
        except Exception:
            pass
        return resposta

    motivo = resultado.get("reason") or resultado.get("error") or "erro_na_consulta"
    return {
        "status": "ok",
        "message": f"Não consegui concluir a consulta real do extrato FGTS agora. Motivo: {motivo}.",
        "data": resultado,
    }


def process_intelligence_request_persona(
    session_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Persona-aware wrapper for intelligence requests implementing Maria Helena rules.

    This implementation mirrors the original behavior but fetches orchestrator
    and audit logger references at runtime to remain module-import-safe.
    """
    try:
        # 🔍 LOG: Verificar se a função foi chamada e com qual mensagem
        incoming_user_text = (
            payload.get("user_text") or payload.get("text") or payload.get("message")
        )
        logger.info(
            f"📞 PERSONA CALLED: session={session_id}, user_text='{incoming_user_text}'"
        )

        user_text = (
            payload.get("user_text")
            or payload.get("text")
            or payload.get("message")
            or ""
        )

        # 🐛 DEBUG: Log incoming payload para diagnosar fluxo de confirmação
        incoming_fields = payload.get("fields", {})
        logger.info(
            f"🎯 PERSONA INCOMING: user_text='{user_text}', fields={incoming_fields}"
        )

        # Obter referências runtime (inclui cache do orquestrador)
        _intelligence, _audit_logger, process_intel_fn = _get_runtime_refs()
        cache = (
            getattr(_intelligence, "cache", None) if _intelligence is not None else None
        )

        fgts_extrato_detectado = _eh_solicitacao_extrato_fgts(user_text)
        fields_payload = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        cpf_texto = _extrair_cpf_texto(
            str(fields_payload.get("cpf") or payload.get("cpf") or "")
        ) or _extrair_cpf_texto(user_text)

        if fgts_extrato_detectado:
            if not cpf_texto:
                return {
                    "status": "ok",
                    "message": (
                        "Preciso do CPF do cliente para buscar o extrato FGTS oficial. "
                        "Envie o CPF completo, com 11 dígitos ou no formato 000.000.000-00."
                    ),
                }

            try:
                if send_audit is not None:
                    send_audit(
                        "persona.fgts_extrato.request",
                        level="info",
                        context={
                            "session_id": session_id,
                            "cpf": cpf_texto,
                            "message": user_text,
                        },
                    )
            except Exception:
                pass

            return _executar_extrato_fgts_real(session_id, cpf_texto, payload)

        # 🔄 Obter Flask session e pending confirmations store do payload
        flask_session = payload.get("flask_session")
        has_flask_session = flask_session is not None
        pending_confirmations_store = payload.get("pending_confirmations_store", {})

        logger.info(
            f"🔍 Storage: cache={cache is not None}, flask_session={has_flask_session}, store={pending_confirmations_store is not None}"
        )

        # 🔴 CRÍTICO: Verificar PRIMEIRO se há uma confirmação pendente (via cache)
        # Isto deve ser feito ANTES de TODOS os outros checks para garantir prioridade
        confirmation_keywords = [
            "sim",
            "confirmo",
            "ok",
            "sim, pode usar",
            "pode usar",
            "está correto",
            "sim, está certo",
            "confirmado",
            "correto",
            "pode",
            "sim, tudo certo",
            "tudo certo",
            "yes",
        ]
        msg_lower_for_conf = user_text.lower().strip() if user_text else ""
        eh_confirmacao_check = msg_lower_for_conf in confirmation_keywords

        # Recuperar confirmação pendente (cache → Flask session → in-memory store)
        pending_confirmation = None
        if eh_confirmacao_check:
            try:
                cache_key = f"{session_id}:pending_confirmation"

                # 1. Tentar cache do orquestrador
                if cache is not None:
                    logger.info(f"🔍 Recuperando do cache: {cache_key}")
                    pending_confirmation = cache.get(cache_key)

                # 2. Fallback: Flask session
                if (
                    pending_confirmation is None
                    and has_flask_session
                    and flask_session is not None
                ):
                    logger.info(f"🔍 Recuperando da Flask.session: {cache_key}")
                    pending_confirmation = flask_session.get(cache_key)

                # 3. Fallback: In-memory store (mais confiável)
                if (
                    pending_confirmation is None
                    and pending_confirmations_store is not None
                ):
                    logger.info(f"🔍 Recuperando do store in-memory: {session_id}")
                    pending_confirmation = pending_confirmations_store.get(session_id)

                logger.info(
                    f"🔍 CONFIRMATION CHECK: msg='{msg_lower_for_conf}', found={pending_confirmation is not None}"
                )
            except Exception as e:
                logger.warning(f"⚠️ Erro ao recuperar confirmação: {e}", exc_info=True)

        if (
            eh_confirmacao_check
            and pending_confirmation
            and pending_confirmation.get("fields")
        ):
            # Há uma confirmação pendente! Retornar imediatamente
            confirmed_fields = pending_confirmation.get("fields", {})

            logger.info(
                f"✅ EARLY CONFIRMATION DETECTED: session={session_id}, fields={confirmed_fields}"
            )
            return {
                "status": "confirmed",
                "fields": confirmed_fields,
                "message": f"Valores confirmados. Processando cálculo com: {', '.join([f'{k}: {v}' for k, v in confirmed_fields.items()])}",
            }
        prior = None
        cache = (
            getattr(_intelligence, "cache", None) if _intelligence is not None else None
        )
        try:
            if cache is not None and hasattr(cache, "get"):
                prior = cache.get(session_id)
        except Exception:
            prior = None

        # 🎯 NOVO: Detectar mensagens vagas com intenção específica detectada
        intencao_tipo = payload.get("intencao_tipo")
        intencao_confianca = payload.get("intencao_confianca", 0.5)

        if intencao_tipo and intencao_tipo != "conversa":
            # Mensagem vaga mas com intenção detectada (ex: "tenho uma dúvida" → tipo=ferias)
            msg_lower = user_text.lower().strip()
            vaga_patterns = [
                "tenho uma dúvida",
                "tenho um dúvida",
                "tenho uma duvida",  # sem acento
                "tenho um duvida",  # sem acento
                "qual é",
                "qual e",  # sem acento
                "quanto é",
                "quanto e",  # sem acento
                "como funciona",
                "como calcula",
                "preciso de",
                "pode me ajudar",
                "o que é",
                "o que e",  # sem acento
                "como é",
                "como e",  # sem acento
            ]

            if any(pattern in msg_lower for pattern in vaga_patterns):
                # Responder especificamente baseado na intenção detectada
                respostas_por_tipo = {
                    "ferias": "Ótimo! Vou ajudar você com o cálculo de férias. Qual é o salário base? 💰",
                    "rescisao": "Entendi que você precisa de ajuda com rescisão. Qual é o valor do salário e há quanto tempo trabalha? 📋",
                    "decimo_terceiro": "Vou calcular seu 13º! Qual é o salário? 🎁",
                    "folha_pagamento": "Certo! Para calcular a folha, preciso do salário bruto. Qual é? 💵",
                    "inss": "Vou ajudá-lo com a contribuição ao INSS. Qual é a remuneração? 🏛️",
                    "fgts": "Sobre FGTS! Qual é o valor base para cálculo? 📊",
                    "imposto": "Vou orientá-lo sobre impostos. Qual é sua renda? 📈",
                    "admissao": "Para o processo de admissão, preciso dos dados do funcionário. Qual é o salário inicial? 👤",
                    "transferencia": "Sobre transferência! Qual é o motivo e qual o novo local/posição? 🔄",
                }

                msg = respostas_por_tipo.get(
                    intencao_tipo, "Certo! Vou ajudá-lo. Mais detalhes, por favor? 📝"
                )
                return {"status": "ok", "message": msg}

        # Resume greeting when context exists
        if prior and isinstance(prior, dict):
            last_value = None
            for candidate in ("pro_labore", "salario_bruto", "salario", "salario_base"):
                if candidate in prior:
                    last_value = prior.get(candidate)
                    break
            if last_value is not None:
                try:
                    msg_val = format_brl(float(last_value))
                except Exception:
                    msg_val = str(last_value)
                welcome = f"Bem-vindo de volta! Da última vez estávamos analisando seu pró-labore de {msg_val}. Quer continuar de onde paramos ou ajustar algum dado?"
                try:
                    if _audit_logger is not None and hasattr(_audit_logger, "log"):
                        _audit_logger.log(
                            {
                                "event": "persona.resume",
                                "session_id": session_id,
                                "value": str(last_value),
                            }
                        )
                except Exception:
                    pass
                return {"status": "resume", "message": welcome, "prior": prior}

        # 🎯 NOVO: Detectar perguntas genéricas/de ajuda SEM intenção específica detectada
        # Se a pessoa faz pergunta vaga SEM mencionar tipo específico, explicar capacidades
        if intencao_tipo == "conversa" or intencao_tipo is None:
            msg_lower = user_text.lower().strip()

            # Padrões de perguntas genéricas/de ajuda
            generic_help_patterns = [
                "tenho uma dúvida",
                "tenho um dúvida",
                "tenho uma duvida",
                "tenho um duvida",
                "preciso de ajuda",
                "pode me ajudar",
                "o que você faz",
                "o que você pode fazer",
                "o que voce faz",
                "o que voce pode fazer",
                "o que você sabe fazer",
                "o que voce sabe fazer",
                "sabe fazer",
                "como você funciona",
                "como voce funciona",
                "como você pode me ajudar",
                "como voce pode me ajudar",
                "o que sabe fazer",
                "qual é sua especialidade",
                "qual e sua especialidade",
                "me ajude",
                "ajudeme",
                "pode ajudar",
                "ajuda com",
                "dúvida sobre",
                "duvida sobre",
                "não sei",
                "nao sei",
                "não entendo",
                "nao entendo",
                "oi, tudo bem",
                "olá, tudo bem",
                "oi, pode me ajudar",
                "olá, pode me ajudar",
                "bom dia",
                "boa tarde",
                "boa noite",
                "oi",
                "olá",
            ]

            # Verificar se é pergunta genérica/de ajuda
            eh_pergunta_generica = any(
                pattern in msg_lower for pattern in generic_help_patterns
            )

            if eh_pergunta_generica:
                # Retornar explicação das capacidades de Maria Helena
                capabilities_msg = """Sou Maria Helena, especialista em cálculos trabalhistas e tributários.

Posso ajudar com:
• Cálculo de 13º salário
• Férias e adicionais de férias
• Rescisão e aviso prévio
• Folha de pagamento
• INSS e contribuições sociais
• Impostos (IRRF, IRPF)
• FGTS
• Admissão de funcionários
• Transferência de funcionários
• Orientação tributária e fiscal
• Geração de documentos contábeis

Envie sua pergunta ou cálculo específico. Por exemplo: "Calcule meu 13º salário com salário R$ 3.000,00 e 8 meses"."""

                try:
                    if send_audit is not None:
                        send_audit(
                            "persona.generic_question",
                            level="info",
                            context={
                                "session_id": session_id,
                                "question": user_text,
                            },
                        )
                except Exception:
                    pass

                return {
                    "status": "ok",
                    "message": capabilities_msg,
                }

        # Summary on demand
        if (
            payload.get("action") == "summary"
            or "o que ja" in user_text.lower()
            or "o que já" in user_text.lower()
        ):
            summary_list = {}
            try:
                if cache is not None and hasattr(cache, "history"):
                    try:
                        hist = cache.history(session_id)
                        summary_list = hist if hist else (prior or {})
                    except Exception:
                        summary_list = prior or {}
                else:
                    summary_list = prior or {}
            except Exception:
                summary_list = prior or {}

            pretty = {}
            for k, v in (summary_list or {}).items():
                try:
                    pretty[k] = (
                        format_brl(float(v))
                        if (
                            isinstance(v, (int, float))
                            or (
                                isinstance(v, str)
                                and v.replace(".", "").replace(",", "").isdigit()
                            )
                        )
                        else v
                    )
                except Exception:
                    pretty[k] = v
            msg = f"Até o momento, registrei: {pretty}. Estamos agora analisando a próxima etapa. Deseja ajustar algo?"
            return {"status": "summary", "message": msg, "data": pretty}

        # Multiple fields aggregation
        fields = (
            payload.get("fields") if isinstance(payload.get("fields"), dict) else None
        )
        if fields and len(fields.keys()) > 1:
            # ✅ NOVO: Se user_text é confirmação E já temos múltiplos campos, processar ao invés de pedir confirmação novamente
            import re as _re

            msg_lower = str(user_text).lower().strip() if user_text else ""
            confirmacao_patterns = [
                r"^(sim|certo|ok|gera|gere|pode|confirmo|isso|tudo certo|está certo|correto)$",
                r"\b(gera|gere|pode gerar|confirmo|confirmar)\b",
            ]
            eh_confirmacao_entrada = any(
                _re.search(p, msg_lower) for p in confirmacao_patterns
            )

            if eh_confirmacao_entrada and fields:
                # Confirmação recebida com dados completos - permitir que processar_com_inteligencia faça o cálculo
                try:
                    _audit_logger.log(
                        {
                            "event": "persona.confirmation_proceed",
                            "session_id": session_id,
                            "fields": fields,
                        }
                    )
                except:
                    pass
                return {
                    "status": "ok",
                    "message": "Certo! Processando o cálculo com os dados registrados.",
                    "data": fields,
                }

            # Se não é confirmação, fazer a agregação normal
            parts = []
            for k, v in fields.items():
                try:
                    ok, parsed = parse_brl_to_float(_normalize_k_suffix(str(v)))
                    if ok:
                        parts.append(f"{k}: {format_brl(parsed)}")
                    else:
                        parts.append(f"{k}: {v}")
                except Exception:
                    parts.append(f"{k}: {v}")
            agg = ", ".join(parts)
            msg = f"Registrei {agg}. Deseja utilizar todos esses valores na análise de hoje?"
            try:
                if send_audit is not None:
                    try:
                        send_audit(
                            "persona.aggregate",
                            level="info",
                            context={"session_id": session_id, "fields": fields},
                        )
                    except Exception:
                        send_audit(
                            {
                                "event": "persona.aggregate",
                                "session_id": session_id,
                                "fields": fields,
                            }
                        )
            except Exception:
                pass

            # Guardar confirmação pendente no cache, Flask session ou in-memory store
            cache_key = f"{session_id}:pending_confirmation"
            data_to_cache = {
                "fields": fields,
                "type": "aggregated",
                "timestamp": __import__("time").time(),
            }

            if cache is not None:
                try:
                    logger.info(f"💾 Salvando no cache com chave: {cache_key}")
                    cache.set(cache_key, data_to_cache)
                    logger.info(
                        f"💾 Confirmação pendente armazenada no cache: {session_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Erro ao armazenar confirmação no cache: {e}", exc_info=True
                    )
            elif has_flask_session and flask_session is not None:
                try:
                    logger.info(f"💾 Salvando em Flask.session com chave: {cache_key}")
                    flask_session[cache_key] = data_to_cache
                    flask_session.modified = True
                    logger.info(
                        f"💾 Confirmação pendente armazenada em Flask.session: {session_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Erro ao armazenar em Flask.session: {e}", exc_info=True
                    )

            # Sempre armazenar no store in-memory como fallback
            if pending_confirmations_store is not None:
                try:
                    logger.info(f"💾 Salvando no store in-memory: {session_id}")
                    pending_confirmations_store[session_id] = data_to_cache
                    logger.info(
                        f"💾 Confirmação pendente armazenada no store: {session_id}"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao armazenar no store: {e}", exc_info=True)

            return {"status": "awaiting_confirmation", "message": msg, "fields": fields}

        # Approximate value handling
        if user_text and _is_approximate_text(user_text):
            text_norm = _normalize_k_suffix(user_text)
            ok, parsed = parse_brl_to_float(text_norm)
            if ok:
                formatted = format_brl(parsed)
                msg = f"Entendi que o valor é aproximado. Para seguirmos com a precisão que a auditoria exige, você confirma {formatted} ou prefere verificar o valor exato?"
                try:
                    if _audit_logger is not None and hasattr(_audit_logger, "log"):
                        _audit_logger.log(
                            {
                                "event": "persona.approximate_detected",
                                "session_id": session_id,
                                "candidate": formatted,
                            }
                        )
                except Exception:
                    pass
                try:
                    if send_audit is not None:
                        try:
                            send_audit(
                                "persona.approximate",
                                level="warning",
                                context={
                                    "session_id": session_id,
                                    "text": user_text,
                                    "candidate": formatted,
                                },
                            )
                        except Exception:
                            send_audit(
                                {
                                    "event": "persona.approximate",
                                    "session_id": session_id,
                                    "text": user_text,
                                    "candidate": formatted,
                                }
                            )
                except Exception:
                    pass

                # Guardar confirmação pendente no cache, Flask session ou in-memory store
                cache_key = f"{session_id}:pending_confirmation"
                data_to_cache = {
                    "candidate": formatted,
                    "type": "approximate",
                    "timestamp": __import__("time").time(),
                }

                if cache is not None:
                    try:
                        cache.set(cache_key, data_to_cache)
                        logger.info(
                            f"💾 Confirmação aproximada armazenada no cache: {session_id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Erro ao armazenar confirmação aproximada no cache: {e}"
                        )
                elif has_flask_session and flask_session is not None:
                    try:
                        flask_session[cache_key] = data_to_cache
                        flask_session.modified = True
                        logger.info(
                            f"💾 Confirmação aproximada armazenada em Flask.session: {session_id}"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Erro ao armazenar em Flask.session: {e}")

                # Sempre armazenar no store in-memory como fallback
                if pending_confirmations_store is not None:
                    try:
                        pending_confirmations_store[session_id] = data_to_cache
                        logger.info(
                            f"💾 Confirmação aproximada armazenada no store: {session_id}"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Erro ao armazenar no store: {e}")

                return {
                    "status": "awaiting_confirmation",
                    "message": msg,
                    "candidate": formatted,
                }

        # 🎯 NOVO: Detectar resposta de confirmação positiva ("sim", "confirmo", etc.)
        # Se houver uma confirmação pendente, processar ao invés de continuar para outros blocos

        # Small-talk redirection
        if user_text and _is_small_talk(user_text):
            try:
                msg = "Que bacana! Mas para não perdermos o foco da sua auditoria, vamos continuar com os dados de análise?"
                if _audit_logger is not None and hasattr(_audit_logger, "log"):
                    _audit_logger.log(
                        {
                            "event": "persona.small_talk_redirect",
                            "session_id": session_id,
                            "text": user_text,
                        }
                    )
                return {"status": "redirect", "message": msg}
            except Exception:
                return {
                    "status": "redirect",
                    "message": "Vamos retomar ao foco da auditoria.",
                }

        # Fallback: delegate to intelligence orchestrator
        try:
            if process_intel_fn is not None:
                return process_intel_fn(session_id, payload)
            # if not available, try importing at runtime
            ag = importlib.import_module("contabil_agente.agent_contabil")
            proc = getattr(ag, "process_intelligence_request", None)
            if proc is not None:
                return proc(session_id, payload)
            raise RuntimeError("IntelligenceOrchestrator not available")
        except Exception as e:
            logger.exception("Persona wrapper delegation failed: %s", e)
            return {"status": "error", "error": str(e)}
    except Exception:
        logger.exception("Unhandled error in persona wrapper")
        return {"status": "error"}
