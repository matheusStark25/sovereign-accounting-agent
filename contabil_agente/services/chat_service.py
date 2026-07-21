"""
ChatService - Lógica de processamento de chat com IA
Encapsula toda interação com LLM e gerenciamento de prompts
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

# Blindagem de importações internas — não devemos falhar no import do módulo
HAS_APPCONFIG = True
HAS_PROMPTS = True
HAS_SESSION = True
HAS_VALIDATION = True
try:
    from core.app_config import AppConfig
except Exception:
    HAS_APPCONFIG = False
    AppConfig = None

try:
    from core.prompts import get_system_prompt
except Exception:
    HAS_PROMPTS = False

    def get_system_prompt():
        return "Maria Helena - Assistente Contábil (prompt padrão)"


try:
    from services.session_service import session_service
except Exception:
    HAS_SESSION = False
    session_service = None

try:
    from services.validation_service import validation_service
except Exception:
    HAS_VALIDATION = False
    validation_service = None


# Lazy import for Groq (Python 3.14 fix)
def _import_groq():
    """Importa Groq de forma lazy para evitar erro no Python 3.14"""
    global Groq
    try:
        from groq import Groq

        return True
    except Exception as e:
        logging.error(f"Erro ao importar Groq: {e}")
        return False


# Import validation service (com fallback suave)
try:
    from services.validation_service import validation_service
except ImportError:
    validation_service = None


logger = logging.getLogger(__name__)


def validar_cpf(cpf: str) -> bool:
    """Valida formato básico de CPF (11 dígitos)"""
    if not cpf or not isinstance(cpf, str):
        return False
    cpf_numeros = re.sub(r"[^\d]", "", cpf)
    return len(cpf_numeros) == 11 and cpf_numeros.isdigit()


def validar_data(data: str) -> bool:
    """Valida formato de data (DD/MM/YYYY ou DD-MM-YYYY)"""
    if not data or not isinstance(data, str):
        return False
    try:
        datetime.strptime(data, "%d/%m/%Y")
        return True
    except ValueError:
        try:
            datetime.strptime(data, "%d-%m-%Y")
            return True
        except ValueError:
            return False


def validar_nome(nome: str) -> bool:
    """Valida formato básico de nome (pelo menos 2 palavras, letras e espaços)"""
    if not nome or not isinstance(nome, str) or len(nome.strip()) < 3:
        return False
    # Deve ter pelo menos 2 palavras, só letras e espaços
    partes = nome.strip().split()
    return len(partes) >= 2 and all(
        re.match(r"^[a-zA-ZÀ-ÿ\s]+$", parte) for parte in partes
    )


class _MemorySessionStore:
    """Fallback em memória simples para gerenciar sessões quando
    `services.session_service` não está disponível.
    Estrutura mínima compatível com o uso no ChatService.
    """

    def __init__(self):
        self._store = {}
        import threading

        self._lock = threading.Lock()

    def get_session(self, session_id: str):
        with self._lock:
            return self._store.get(session_id)

    def create_session(
        self, session_id: str, messages=None, context=None, profile=None
    ):
        with self._lock:
            sess = {
                "id": session_id,
                "messages": messages or [],
                "contexto": context or {},
                "profile": profile,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._store[session_id] = sess
            return sess

    def update_session(self, session_id: str, messages=None, context=None):
        with self._lock:
            s = self._store.get(session_id)
            if not s:
                return None
            if messages is not None:
                s["messages"] = messages
            if context is not None:
                s["contexto"] = context
            return s

    def add_message(self, session_id: str, role: str, content: str):
        with self._lock:
            s = self._store.get(session_id)
            if not s:
                s = self.create_session(
                    session_id,
                    messages=[{"role": "system", "content": get_system_prompt()}],
                    context={},
                )
            s.setdefault("messages", []).append(
                {
                    "role": role,
                    "content": content,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            return True


class ChatService:
    """
    Serviço responsável por processar mensagens de chat
    Gerencia comunicação com LLM e construção de prompts
    """

    # Lazy singleton support
    _instance = None
    _instance_lock = None

    @classmethod
    def get_instance(cls, config: Optional[Dict] = None):
        """Retorna instância lazy do serviço. Aceita `config` para sobrepor defaults."""
        if cls._instance is None:
            # Import local to avoid adding threading in module import
            import threading

            if cls._instance is None:
                cls._instance_lock = threading.Lock()
                with cls._instance_lock:
                    if cls._instance is None:
                        cls._instance = cls(config or {})
        return cls._instance

    def __init__(self, config: Optional[Dict] = None):
        """Inicializa o serviço de chat.

        Config hierarchy (priority):
        - explicit `config` dict passed to constructor
        - environment variables
        - AppConfig (if available)
        - hardcoded defaults
        """
        cfg = config or {}

        # Defaults (safe out-of-the-box)
        default = {
            "groq_api_key": os.getenv("GROQ_API_KEY")
            or (getattr(AppConfig, "GROQ_API_KEY", None) if HAS_APPCONFIG else None),
            "model": os.getenv("AI_MODEL")
            or (getattr(AppConfig, "AI_MODEL", "gpt-3") if HAS_APPCONFIG else "gpt-3"),
            "temperature": float(os.getenv("AI_TEMPERATURE", "0.5")),
            "max_tokens": int(os.getenv("AI_MAX_TOKENS", "512")),
            "top_p": float(os.getenv("AI_TOP_P", "1.0")),
            "stateless": cfg.get("stateless", False),
            "offline": cfg.get("offline", False),
            "cb_failure_threshold": int(cfg.get("cb_failure_threshold", 3)),
            "cb_reset_seconds": int(cfg.get("cb_reset_seconds", 60)),
        }

        # Final config values
        self.api_key = cfg.get("groq_api_key", default["groq_api_key"])
        self.model = cfg.get("model", default["model"])
        self.temperature = cfg.get("temperature", default["temperature"])
        self.max_tokens = cfg.get("max_tokens", default["max_tokens"])
        self.top_p = cfg.get("top_p", default["top_p"])
        self.stateless = cfg.get("stateless", default["stateless"])
        self.offline = cfg.get("offline", default["offline"])

        # Groq client is created lazily
        self.client = None

        # Circuit Breaker state for Groq
        self._cb_failures = 0
        self._cb_failure_threshold = cfg.get(
            "cb_failure_threshold", default["cb_failure_threshold"]
        )
        self._cb_reset_seconds = cfg.get(
            "cb_reset_seconds", default["cb_reset_seconds"]
        )
        self._cb_opened_at: Optional[datetime] = None

        # Session service fallback: if session_service not loaded, create in-memory store
        if session_service is None:
            logger.warning(
                json.dumps(
                    {
                        "fallback": "session_service_missing",
                        "action": "using_memory_session",
                    }
                )
            )
            self._session_store = _MemorySessionStore()
            self._using_memory_session = True
        else:
            self._session_store = session_service
            self._using_memory_session = False

        # Validation service availability
        if validation_service is None:
            logger.warning(
                json.dumps(
                    {
                        "fallback": "validation_service_missing",
                        "action": "using_internal_simple_validation",
                    }
                )
            )
            self._validation = None
        else:
            self._validation = validation_service

    # -- Session accessors delegating to chosen store
    def _get_session(self, session_id: str):
        return self._session_store.get_session(session_id)

    def _create_session(
        self, session_id: str, messages=None, context=None, profile=None
    ):
        return self._session_store.create_session(
            session_id, messages=messages, context=context, profile=profile
        )

    def _update_session(self, session_id: str, messages=None, context=None):
        return self._session_store.update_session(
            session_id, messages=messages, context=context
        )

    def _add_message(self, session_id: str, role: str, content: str):
        return self._session_store.add_message(session_id, role, content)

    def build_system_prompt(self) -> str:
        """
        Constrói o system prompt da Maria Helena
        Centralizado aqui para fácil manutenção
        """
        # Retornar a versão canônica desde core.prompts
        return get_system_prompt()

    def process_message(
        self, session_id: str, message: str, context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Processa uma mensagem do usuário

        Args:
            session_id: ID da sessão
            message: Mensagem do usuário
            context: Contexto adicional extraído da mensagem

        Returns:
            Dict com resposta e metadados
        """
        # Recuperar ou criar sessão via store (pode ser memória)
        session = self._get_session(session_id)

        if not session:
            # Nova sessão - criar com system prompt
            system_prompt = self.build_system_prompt()
            session = self._create_session(
                session_id=session_id,
                messages=[{"role": "system", "content": system_prompt}],
                context=context or {},
                profile="neutro",
            )
        else:
            # Sessão existe - atualizar system prompt (sempre usa o mais atual)
            system_prompt = self.build_system_prompt()
            messages = session.get("messages", [])

            # Remove system prompts antigos
            messages = [msg for msg in messages if msg.get("role") != "system"]

            # Adiciona novo system prompt no início
            messages.insert(0, {"role": "system", "content": system_prompt})

            # Atualiza contexto se fornecido
            if context:
                ctx = session.get("contexto") or {}
                ctx.update(context)
                session["contexto"] = ctx

            # Salva de volta
            try:
                self._update_session(
                    session_id, messages=messages, context=session.get("contexto")
                )
            except Exception:
                logger.warning(
                    json.dumps(
                        {
                            "fallback": "update_session_failed",
                            "action": "continuing_without_persist",
                        }
                    )
                )
            session = self._get_session(session_id)

        # Validar dados extraídos da mensagem se houver
        dados_extraidos = self._extrair_dados_mensagem(message)
        if dados_extraidos:
            # Atualizar contexto com dados validados
            for chave, valor in dados_extraidos.items():
                if chave == "cp" and not validar_cpf(valor):
                    logger.warning(f"CPF inválido detectado: {valor}")
                elif chave == "data" and not validar_data(valor):
                    logger.warning(f"Data inválida detectada: {valor}")
                elif chave == "nome" and not validar_nome(valor):
                    logger.warning(f"Nome inválido detectado: {valor}")
                else:
                    ctx = session.get("contexto") or {}
                    ctx[chave] = valor
                    session["contexto"] = ctx

        # Montar mensagem do usuário com contexto
        context_str = json.dumps(session.get("contexto", {}), ensure_ascii=False)
        user_message = f"CONTEXTO: {context_str}\n\nPERGUNTA: {message}"

        # Adicionar mensagem do usuário
        try:
            self._add_message(session_id, "user", user_message)
        except Exception:
            logger.warning(
                json.dumps(
                    {"fallback": "add_message_failed", "action": "in_memory_append"}
                )
            )

        # Recarregar sessão com a nova mensagem
        session = self._get_session(session_id)

        try:
            # Chamar LLM via wrapper que implementa Circuit Breaker
            response = None

            if self.offline:
                logger.warning(
                    json.dumps(
                        {
                            "fallback": "offline_mode",
                            "action": "returning_local_fallback",
                        }
                    )
                )
                response = (
                    "Olá! Estou em modo offline e não consigo acessar o serviço de IA. "
                    "Por favor, tente novamente mais tarde."
                )

            else:
                try:
                    response = self._call_groq_and_get_response(session)
                except Exception as e:
                    logger.warning(
                        json.dumps({"fallback": "groq_call_failed", "error": str(e)})
                    )
                    # fallback mock
                    response = (
                        "Olá! Resposta fallback: não foi possível obter resposta da IA agora. "
                        "Tente novamente em alguns instantes."
                    )

            # Verificar se caso requer validação CRC
            validation_info = None
            if self._validation:
                try:
                    requires_validation, categoria, motivo = (
                        self._validation.requires_crc_validation(message, response)
                    )

                    if requires_validation:
                        validation_msg = self._validation.get_validation_message(
                            categoria, motivo
                        )
                        # Adiciona mensagem de validação à resposta
                        response = f"{response}\n\n{validation_msg}"

                        validation_info = {
                            "requires_validation": True,
                            "category": categoria,
                            "reason": motivo,
                        }
                        logger.warning(
                            json.dumps(
                                {"validation_required": categoria, "reason": motivo}
                            )
                        )
                except Exception as e:
                    logger.warning(
                        json.dumps(
                            {
                                "validation_error": str(e),
                                "action": "skipping_validation",
                            }
                        )
                    )

            try:
                self._add_message(session_id, "assistant", response)
            except Exception:
                logger.warning(json.dumps({"fallback": "add_assistant_message_failed"}))

            # Gerenciar tamanho do histórico
            try:
                self._trim_session_history(session_id)
            except Exception:
                logger.debug("_trim_session_history falhou; ignorando")

            logger.info(f"✅ Chat processado - Session: {session_id[:8]}")

            result = {
                "success": True,
                "response": response,
                "session_id": session_id,
                "message_count": len(session.get("messages", [])),
            }

            # Adiciona info de validação se necessário
            if validation_info:
                result["validation"] = validation_info

            return result

        except Exception as e:
            logger.error(f"❌ Erro ao processar chat: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": "Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente.",
            }

    def _trim_session_history(self, session_id: str):
        """
        Mantém apenas as últimas N mensagens + system prompt
        Evita crescimento infinito do histórico
        """
        session = self._get_session(session_id)
        if not session:
            return
        messages = session.get("messages", [])
        max_messages = 50 + 1  # safe default if AppConfig unavailable
        if HAS_APPCONFIG and AppConfig is not None:
            try:
                max_messages = (
                    getattr(AppConfig, "MAX_SESSION_MESSAGES", max_messages) + 1
                )
            except Exception:
                pass

        if len(messages) > max_messages:
            # Manter system prompt (primeiro) + últimas N mensagens
            trimmed = [messages[0]] + messages[-(max_messages - 1) :]
            try:
                self._update_session(session_id, messages=trimmed)
            except Exception:
                logger.warning(json.dumps({"fallback": "trim_update_failed"}))
            logger.info(f"🗑️ Histórico trimmed - Session: {session_id[:8]}")

    def _extrair_dados_mensagem(self, message: str) -> Dict[str, Any]:
        """Extrai dados simples da mensagem do usuário.

        Retorna um dict com chaves potenciais: `cpf`, `data`, `nome`, `salario`, `posto`.
        Método intencionalmente simples — serve como fallback leve para popular contexto.
        """
        if not message or not isinstance(message, str):
            return {}

        dados = {}

        # CPF (formato com pontos e traço ou apenas 11 dígitos)
        cpf_match = re.search(r"(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})", message)
        if cpf_match:
            cpf = re.sub(r"\D", "", cpf_match.group(0))
            dados["cp"] = cpf

        # Datas no formato DD/MM/YYYY, DD-MM-YYYY ou DD/MM
        date_match = re.search(r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b", message)
        if date_match:
            dados["data"] = date_match.group(1)

        # Salário — procura por 'salario' seguido de valor ou R$ valor
        sal_match = re.search(r"(?i)sal[áa]rio[:\s]*R?\$?\s*([\d\.,]+)", message)
        if not sal_match:
            sal_match = re.search(r"R\$\s*([\d\.,]+)", message)
        if sal_match:
            val = sal_match.group(1).strip()
            # Normalizar '1.234,56' -> '1234.56'
            normalized = val.replace(".", "").replace(",", ".")
            dados["salario"] = normalized

        # Nome (se houver label 'Nome:')
        nome_match = re.search(
            r"(?i)nome[:\s]*([A-ZÀ-Ýa-zà-ÿ][A-Za-zÀ-ÿ'\-\s]+)", message
        )
        if nome_match:
            dados["nome"] = nome_match.group(1).strip()

        # Posto / novo posto
        posto_match = re.search(
            r"(?i)(?:novo\s+posto|posto|local)[\s:]*([A-Za-zÀ-ÿ0-9\-\s]+)", message
        )
        if posto_match:
            dados["posto"] = posto_match.group(1).strip()

        return dados

    # --- Circuit Breaker and Groq wrapper ---
    def _is_circuit_open(self) -> bool:
        if self._cb_opened_at is None:
            return False
        if datetime.now(timezone.utc) - self._cb_opened_at > timedelta(
            seconds=self._cb_reset_seconds
        ):
            # Reset circuito
            self._cb_opened_at = None
            self._cb_failures = 0
            return False
        return True

    def _record_failure(self):
        self._cb_failures += 1
        if self._cb_failures >= self._cb_failure_threshold:
            self._cb_opened_at = datetime.now(timezone.utc)
            logger.warning(
                json.dumps({"circuit_breaker": "opened", "failures": self._cb_failures})
            )

    def _record_success(self):
        if self._cb_failures > 0:
            self._cb_failures = 0
        self._cb_opened_at = None

    def _call_groq_and_get_response(self, session: Dict[str, Any]) -> str:
        """Tenta chamar Groq respeitando o Circuit Breaker; retorna texto."""
        # Se circuito aberto, falhar rápido
        if self._is_circuit_open():
            raise RuntimeError("Circuit breaker aberto para Groq")

        # Lazy import/creation of client
        if self.client is None:
            try:
                if _import_groq():
                    from groq import Groq

                    key = self.api_key or os.getenv("GROQ_API_KEY")
                    if not key:
                        raise RuntimeError("GROQ_API_KEY não configurada")
                    self.client = Groq(api_key=key)
            except Exception:
                self._record_failure()
                raise

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=session.get("messages", []),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
            )
            self._record_success()
            return completion.choices[0].message.content
        except Exception:
            self._record_failure()
            raise

    def check_health(self) -> Dict[str, Any]:
        """Retorna um dict com o estado das dependências do ChatService."""
        health = {
            "session_service": (
                "memory" if getattr(self, "_using_memory_session", False) else "ok"
            ),
            "validation_service": "missing" if self._validation is None else "ok",
            "groq_circuit_open": bool(self._is_circuit_open()),
            "offline_mode": bool(self.offline),
        }
        return health


# No global singleton is created at import time. Use `ChatService.get_instance()`.
