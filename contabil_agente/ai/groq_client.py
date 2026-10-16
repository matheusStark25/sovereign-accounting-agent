"""
Cliente Groq com suporte a async e cache
"""

import asyncio
import hashlib
import time
from types import SimpleNamespace
from typing import Any, Dict, Optional

import structlog
import os
from cachetools import TTLCache
import json
import time as _time

# Tenacity for robust retry policy
try:
    from tenacity import (
        retry,
        wait_exponential,
        stop_after_attempt,
        RetryError,
        retry_if_exception_type,
    )
except Exception:
    # If tenacity is not available, we'll fall back to internal retry loop below
    retry = None
    wait_exponential = None
    stop_after_attempt = None
    RetryError = Exception

from ..config.settings import Config
import re

# Optional import of httpx exception types for tenacity filtering
try:
    import httpx

    _HTTPX_TIMEOUT_EX = httpx.TimeoutException
    _HTTPX_STATUS_EX = httpx.HTTPStatusError
except Exception:
    httpx = None
    _HTTPX_TIMEOUT_EX = None
    _HTTPX_STATUS_EX = None


# Lazy import for Groq (Python 3.14 fix)
def _import_groq():
    """Importa Groq de forma lazy para evitar erro no Python 3.14"""
    global Groq, AsyncGroq, APIConnectionError, APIError, RateLimitError
    # If tests or environment pre-set these symbols (mocking), don't re-import.
    if Groq is not None:
        return True

    try:
        from groq import APIConnectionError, APIError, AsyncGroq, Groq, RateLimitError

        return True
    except Exception as e:
        import logging

        logging.error(f"Erro ao importar Groq: {e}")
        return False


# Expose symbols at module level so tests can patch them even if Groq client
# library isn't installed. Tests will patch these names with mocks.
Groq = None
AsyncGroq = None
APIConnectionError = Exception
APIError = Exception
RateLimitError = Exception


logger = structlog.get_logger(__name__)

# Cache de respostas LLM (1000 items, expira em 1 hora)
_MODULE_CACHE_TTL = 3600


class GroqClient:
    """Cliente Groq com retry, circuit breaker e cache"""

    def __init__(self, api_key: Optional[str] = None):
        # Allow overriding api_key for tests
        self.api_key = api_key or Config.GROQ_API_KEY
        self.model = Config.MODEL_NAME
        self.temperature = Config.TEMPERATURE
        # Provide lightweight stubs so tests can patch nested attributes
        self.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda *a, **k: None)
            )
        )
        self.async_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda *a, **k: None)
            )
        )
        # Mark these stubs so we can detect and replace them when a
        # module-level Groq/AsyncGroq is patched during a test.
        try:
            self.client._is_default_stub = True
        except Exception:
            pass
        try:
            self.async_client._is_default_stub = True
        except Exception:
            pass
        # If a module-level mock is present at construction time (common in
        # tests that use the @patch decorator), instantiate real clients so
        # the test's mocked classes are honored consistently.
        try:
            if Groq is not None:
                self.client = Groq(api_key=self.api_key)
        except Exception:
            pass
        try:
            if AsyncGroq is not None:
                self.async_client = AsyncGroq(api_key=self.api_key)
            if Groq is not None:
                try:
                    # Prefer minimal, explicit construction to avoid passing
                    # unexpected kwargs to the underlying SDK across versions.
                    # Start with the minimal `api_key` argument only.
                    self.client = Groq(api_key=self.api_key)
                    return self.client
                except TypeError as e:
                    # If the SDK implementation changed and rejects unexpected
                    # kwargs, log and retry with only the api_key explicitly.
                    logger.warning("groq_client_init_typeerror", error=str(e))
                    try:
                        self.client = Groq(self.api_key)
                        return self.client
                    except Exception:
                        logger.error("erro_criar_cliente_groq", error=str(e))
                        raise
        except Exception:
            # If any of the above client initialization attempts fail,
            # continue with the default stubs and allow lazy init later.
            pass
        self.failure_count = 0
        self.failure_threshold = 3
        self.recovery_timeout = 60
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

        # Backwards-compatible circuit_breaker proxy expected by tests.
        # Use a small proxy object so `.state` and `.failure_count` always
        # reflect the live values on the GroqClient instance.
        class _CircuitBreakerProxy:
            def __init__(self, owner: "GroqClient") -> None:
                self._owner = owner

            @property
            def state(self) -> str:
                return self._owner.state

            @state.setter
            def state(self, v: str) -> None:
                self._owner.state = v

            @property
            def failure_count(self) -> int:
                return self._owner.failure_count

            @failure_count.setter
            def failure_count(self, v: int) -> None:
                self._owner.failure_count = v

            @property
            def recovery_timeout(self) -> int:
                return self._owner.recovery_timeout

            @recovery_timeout.setter
            def recovery_timeout(self, v: int) -> None:
                self._owner.recovery_timeout = v

        self.circuit_breaker = _CircuitBreakerProxy(self)

        # Per-instance cache to avoid cross-test pollution
        try:
            self.cache = TTLCache(maxsize=1000, ttl=_MODULE_CACHE_TTL)
        except Exception:
            # Fallback to dict-like object if cachetools not available
            self.cache = {}

    def _get_client(self):
        """Obtém cliente síncrono"""
        # If we have an existing client and it's the default stub, allow
        # replacing it when a module-level Groq mock is present (typical
        # in tests that patch Groq before creating a client).
        if getattr(self.client, "chat", None) is not None:
            if Groq is not None and getattr(self.client, "_is_default_stub", False):
                try:
                    self.client = Groq(api_key=self.api_key)
                    # replaced default stub with module-level Groq
                    return self.client
                except Exception:
                    pass
            return self.client

        # If stub is missing, try to create a real client (respecting any
        # module-level Groq mock when present).
        if Groq is not None:
            try:
                self.client = Groq(api_key=self.api_key)
                return self.client
            except Exception:
                # Fall back to lazy import path if creation fails
                pass

        # Importar Groq de forma lazy (Python 3.14 fix)
        if not _import_groq():
            logger.error("erro_importar_groq", message="Falha ao importar Groq")
            raise RuntimeError("Falha ao importar Groq - verifique dependências")

        try:
            self.client = Groq(api_key=self.api_key)
        except TypeError as e:
            logger.error("erro_criar_cliente_groq", error=str(e))
            raise

        return self.client

    def _get_async_client(self):
        """Obtém cliente assíncrono"""
        # Prefer existing async stub when present (so instance-level patches hold).
        if getattr(self.async_client, "chat", None) is not None:
            # If an AsyncGroq/Groq patch exists and this is the default stub,
            # replace it so tests that patch module-level clients behave as expected.
            if (AsyncGroq is not None or Groq is not None) and getattr(
                self.async_client, "_is_default_stub", False
            ):
                try:
                    if AsyncGroq is not None:
                        self.async_client = AsyncGroq(api_key=self.api_key)
                    else:
                        self.async_client = Groq(api_key=self.api_key)
                    return self.async_client
                except Exception:
                    pass
            return self.async_client

        # Try to create AsyncGroq if available
        if AsyncGroq is not None:
            try:
                self.async_client = AsyncGroq(api_key=self.api_key)
                return self.async_client
            except Exception:
                # If async construction fails, fallthrough to other attempts
                logger.warning("async_groq_init_failed")
                pass

        # Fall back to Groq if patched and usable
        if Groq is not None:
            try:
                self.async_client = Groq(api_key=self.api_key)
                return self.async_client
            except Exception:
                pass

        # Importar Groq de forma lazy (Python 3.14 fix)
        if not _import_groq():
            logger.error(
                "erro_importar_groq_async", message="Falha ao importar AsyncGroq"
            )
            raise RuntimeError("Falha ao importar Groq - verifique dependências")

        try:
            if AsyncGroq is not None:
                try:
                    self.async_client = AsyncGroq(api_key=self.api_key)
                except TypeError as e:
                    logger.warning("async_groq_typeerror", error=str(e))
                    self.async_client = AsyncGroq(self.api_key)
            else:
                try:
                    self.async_client = Groq(api_key=self.api_key)
                except TypeError as e:
                    logger.warning("groq_typeerror_async_fallback", error=str(e))
                    self.async_client = Groq(self.api_key)
        except TypeError:
            # If creation fails, keep default stub
            pass

        return self.async_client

    def _check_circuit_breaker(self):
        """Verifica estado do circuit breaker"""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("circuit_breaker_half_open")
            else:
                raise Exception("Circuit breaker is OPEN")

    def _record_success(self):
        """Registra sucesso na chamada"""
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failure_count = 0
            logger.info("circuit_breaker_closed")
        # keep proxy in sync
        try:
            self.circuit_breaker.state = self.state
            self.circuit_breaker.failure_count = self.failure_count
        except Exception:
            pass

    def _record_failure(self):
        """Registra falha na chamada"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error("circuit_breaker_open", failures=self.failure_count)
        # debug: failure_count updated
        try:
            self.circuit_breaker.state = self.state
            self.circuit_breaker.failure_count = self.failure_count
        except Exception:
            pass

    def _cache_key(self, prompt: str) -> str:
        """Gera chave de cache para o prompt"""
        return hashlib.sha256(prompt.encode()).hexdigest()

    def chamar_groq(
        self,
        prompt: str,
        max_retries: int = 2,
        fallback_text: Optional[
            str
        ] = "Houve um pequeno problema técnico. Vou tentar novamente, ok?",
        use_cache: bool = True,
    ) -> str:
        """
        Chamada síncrona ao Groq com retry e cache

        Args:
            prompt: Prompt para o modelo
            max_retries: Número máximo de tentativas
            fallback_text: Texto de fallback em caso de erro
            use_cache: Se deve usar cache de respostas

        Returns:
            Resposta do modelo
        """
        # Verifica cache (per-instance)
        if use_cache:
            cache_key = self._cache_key(prompt)
            if cache_key in self.cache:
                logger.info("cache_hit", key=cache_key[:12])
                return self.cache[cache_key]

        # Verifica circuit breaker
        try:
            self._check_circuit_breaker()
        except Exception:
            if fallback_text:
                return fallback_text
            raise

        client = self._get_client()

        def _log_attempt_info(
            attempt_no: int,
            elapsed: float,
            status_code: Optional[int],
            resp_text: Optional[str],
        ):
            logger.warning(
                "groq_attempt_info",
                tentativa=attempt_no,
                tempo_resp_s=round(elapsed, 3),
                status_code=status_code,
            )
            if resp_text:
                try:
                    # Audit log: record raw provider response excerpt before sanitization
                    logger.info(
                        "groq_raw_response",
                        tentativa=attempt_no,
                        tempo_resp_s=round(elapsed, 3),
                        status_code=status_code,
                        raw_excerpt=(
                            resp_text[:4096]
                            if isinstance(resp_text, str)
                            else str(resp_text)[:4096]
                        ),
                    )
                except Exception:
                    pass

        def _single_call():
            start = _time.time()
            try:
                # Forced simulation should happen inside the try so the
                # except block logs attempt info and the retry logic sees it.
                if os.getenv("GROQ_FORCE_FAIL", "0") in ("1", "true", "True"):
                    raise _SimulatedProviderException(
                        status_code=500, text="FORCED_SIMULATED_ERROR"
                    )
                resposta = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    max_tokens=800,
                    timeout=30,
                    headers={"Content-Type": "application/json"},
                )
            except Exception as e:
                elapsed = _time.time() - start
                status_code = None
                resp_text = None
                try:
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        status_code = getattr(resp, "status_code", None)
                        resp_text = getattr(resp, "text", None) or getattr(
                            resp, "content", None
                        )
                except Exception:
                    pass
                _log_attempt_info(1, elapsed, status_code, resp_text)
                raise

            elapsed = _time.time() - start
            status_code = getattr(resposta, "status_code", None)
            resp_text = None
            try:
                if hasattr(resposta, "text"):
                    resp_text = resposta.text
                elif hasattr(resposta, "content"):
                    resp_text = resposta.content
                else:
                    resp_text = str(resposta)
            except Exception:
                resp_text = None

            if status_code is not None and status_code != 200:
                _log_attempt_info(1, elapsed, status_code, resp_text)

            try:
                texto = resposta.choices[0].message.content.strip()
            except Exception:
                if isinstance(resp_text, (str, bytes)):
                    rt = (
                        resp_text
                        if isinstance(resp_text, str)
                        else resp_text.decode("utf-8", errors="ignore")
                    )
                    candidate = None
                    try:
                        candidate = _extract_json_via_regex_then_bracematch(rt)
                    except json.JSONDecodeError:
                        # bubble up to allow retry
                        raise
                    except Exception:
                        candidate = None

                    if candidate:
                        try:
                            obj = json.loads(candidate)
                            texto = (
                                obj.get("choices", [{}])[0]
                                .get("message", {})
                                .get("content")
                            )
                            if texto:
                                texto = texto.strip()
                        except json.JSONDecodeError:
                            raise
                        except Exception:
                            texto = rt.strip()
                    else:
                        texto = rt.strip()
                else:
                    texto = str(resposta)

            if not texto:
                raise Exception("Resposta vazia do provedor")

            self._record_success()
            if use_cache:
                try:
                    self.cache[cache_key] = texto
                except Exception:
                    pass
            logger.info(
                "groq_sucesso",
                tentativa=1,
                tamanho_resposta=len(texto),
                cache_usado=use_cache,
            )
            return texto

        if retry is not None:

            # Build exception tuple for retry filtering (prefer httpx types when available)
            _retry_exc_types = (json.JSONDecodeError, _SimulatedProviderException)
            try:
                if _HTTPX_TIMEOUT_EX is not None:
                    _retry_exc_types = tuple(
                        list(_retry_exc_types) + [_HTTPX_TIMEOUT_EX]
                    )
                if _HTTPX_STATUS_EX is not None:
                    _retry_exc_types = tuple(
                        list(_retry_exc_types) + [_HTTPX_STATUS_EX]
                    )
            except Exception:
                pass

            # If tenacity provides retry_if_exception_type, use it to limit retries
            retry_kwargs = {
                "wait": wait_exponential(multiplier=1, min=4, max=10),
                "stop": stop_after_attempt(max_retries + 1),
                "reraise": True,
            }
            try:
                if retry_if_exception_type is not None:
                    retry_kwargs["retry"] = retry_if_exception_type(_retry_exc_types)
            except Exception:
                pass

            @retry(**retry_kwargs)
            def _call_with_retry():
                return _single_call()

            try:
                return _call_with_retry()
            except RetryError as re:
                last = re.last_attempt._exception if hasattr(re, "last_attempt") else re
                self._record_failure()
                try:
                    logger.warning("groq_retries_exhausted", error=str(last))
                except Exception:
                    pass
                if fallback_text:
                    return fallback_text
                raise
            except Exception as e:
                self._record_failure()
                if fallback_text:
                    return fallback_text
                raise

        backoff = [0, 1.5, 3.0]
        for attempt in range(max_retries + 1):
            try:
                return _single_call()
            except Exception as e:
                logger.warning(
                    "groq_attempt_failed",
                    tentativa=attempt + 1,
                    erro=type(e).__name__,
                    mensagem=str(e),
                )
                self._record_failure()
                if attempt == max_retries:
                    logger.error("groq_falha_total", tentativas=max_retries + 1)
                    if fallback_text:
                        return fallback_text
                    raise
                try:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
                except Exception:
                    pass

        return fallback_text or "Erro ao processar sua solicitação."

    async def chamar_groq_async(
        self,
        prompt: str,
        max_retries: int = 2,
        fallback_text: Optional[
            str
        ] = "Houve um pequeno problema técnico. Vou tentar novamente, ok?",
        use_cache: bool = True,
    ) -> str:
        """
        Chamada assíncrona ao Groq (não bloqueia o servidor)

        Args:
            prompt: Prompt para o modelo
            max_retries: Número máximo de tentativas
            fallback_text: Texto de fallback em caso de erro
            use_cache: Se deve usar cache de respostas

        Returns:
            Resposta do modelo
        """
        # Verifica cache (per-instance)
        if use_cache:
            cache_key = self._cache_key(prompt)
            if cache_key in self.cache:
                logger.info("cache_hit_async", key=cache_key[:12])
                return self.cache[cache_key]

        # Verifica circuit breaker
        try:
            self._check_circuit_breaker()
        except Exception:
            if fallback_text:
                return fallback_text
            raise

        client = self._get_async_client()

        async def _single_call_async():
            start = _time.time()
            try:
                # Forced simulation inside the try so the except and retry see it
                if os.getenv("GROQ_FORCE_FAIL", "0") in ("1", "true", "True"):
                    raise _SimulatedProviderException(
                        status_code=500, text="FORCED_SIMULATED_ERROR"
                    )
                maybe = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    max_tokens=800,
                    timeout=30,
                    headers={"Content-Type": "application/json"},
                )
                if asyncio.iscoroutine(maybe):
                    resposta = await maybe
                else:
                    resposta = maybe
            except Exception as e:
                elapsed = _time.time() - start
                status_code = None
                resp_text = None
                try:
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        status_code = getattr(resp, "status_code", None)
                        resp_text = getattr(resp, "text", None) or getattr(
                            resp, "content", None
                        )
                except Exception:
                    pass
                logger.warning(
                    "groq_async_call_failed",
                    tempo_resp_s=round(elapsed, 3),
                    status_code=status_code,
                )
                raise

            elapsed = _time.time() - start
            status_code = getattr(resposta, "status_code", None)
            resp_text = None
            try:
                if hasattr(resposta, "text"):
                    resp_text = resposta.text
                elif hasattr(resposta, "content"):
                    resp_text = resposta.content
                else:
                    resp_text = str(resposta)
            except Exception:
                resp_text = None

            if status_code is not None and status_code != 200:
                logger.warning(
                    "groq_async_non200",
                    tempo_resp_s=round(elapsed, 3),
                    status_code=status_code,
                )

            try:
                texto = resposta.choices[0].message.content.strip()
            except Exception:
                if isinstance(resp_text, (str, bytes)):
                    rt = (
                        resp_text
                        if isinstance(resp_text, str)
                        else resp_text.decode("utf-8", errors="ignore")
                    )
                    # Try regex-first JSON extraction; if it fails, it raises JSONDecodeError
                    candidate = None
                    try:
                        candidate = _extract_json_via_regex_then_bracematch(rt)
                    except json.JSONDecodeError:
                        # re-raise to let tenacity (or outer loop) decide on retry
                        raise
                    except Exception:
                        # fallback: use raw text if other unexpected errors occur
                        candidate = None

                    if candidate:
                        try:
                            obj = json.loads(candidate)
                            texto = (
                                obj.get("choices", [{}])[0]
                                .get("message", {})
                                .get("content")
                            )
                            if texto:
                                texto = texto.strip()
                        except json.JSONDecodeError:
                            # If JSON parsing fails here, raise to trigger retry
                            raise
                        except Exception:
                            texto = rt.strip()
                    else:
                        texto = rt.strip()
                else:
                    texto = str(resposta)

            if not texto:
                raise Exception("Resposta vazia do provedor (async)")

            self._record_success()
            if use_cache:
                try:
                    self.cache[cache_key] = texto
                except Exception:
                    pass
            logger.info("groq_sucesso_async", tamanho_resposta=len(texto))
            return texto

        backoff = [0, 1.5, 3.0]
        for attempt in range(max_retries + 1):
            try:
                return await _single_call_async()
            except Exception as e:
                logger.warning(
                    "groq_async_attempt_failed",
                    tentativa=attempt + 1,
                    erro=type(e).__name__,
                    mensagem=str(e),
                )
                self._record_failure()
                if attempt == max_retries:
                    logger.error("groq_async_falha_total", tentativas=max_retries + 1)
                    if fallback_text:
                        return fallback_text
                    raise
                await asyncio.sleep(backoff[min(attempt, len(backoff) - 1)])

        return fallback_text or "Erro ao processar sua solicitação."

    def limpar_cache(self):
        """Limpa cache de respostas"""
        try:
            self.cache.clear()
        except Exception:
            # fallback for dict-like
            self.cache = {}
        logger.info("cache_limpo")

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do cliente"""
        return {
            "circuit_breaker_state": self.state,
            "circuit_state": self.state,
            "failure_count": self.failure_count,
            "cache_size": len(self.cache),
            "cache_max_size": getattr(self.cache, "maxsize", None),
            "last_failure": self.last_failure_time,
        }


class _SimulatedProviderException(Exception):
    """Exception used to simulate provider failures during testing."""

    def __init__(self, status_code: int = 500, text: str = "SIMULATED ERROR"):
        super().__init__(f"Simulated provider error {status_code}")
        self.response = SimpleNamespace(status_code=status_code, text=text)


def _extract_json_from_text(text: str) -> Optional[str]:
    """Extrai o primeiro objeto JSON bem formado encontrado em `text`.

    Procura o primeiro caracter '{' e tenta casar chaves até fechar o objeto.
    Retorna a substring JSON ou None se não encontrar/parsear.
    """
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '"' and not esc:
            in_string = not in_string
        if in_string and ch == "\\" and not esc:
            esc = True
            continue
        esc = False
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    # validate it's JSON
                    json.loads(candidate)
                    return candidate
                except Exception:
                    return None
    return None


def _extract_json_via_regex_then_bracematch(text: str) -> str:
    """Tenta extrair JSON via regex (r'({.*})', DOTALL) primeiro. Se falhar,
    tenta o extrator robusto por contagem de chaves. Se nenhum funcionar,
    levanta json.JSONDecodeError para sinalizar que o parse falhou.
    """
    if not text:
        raise json.JSONDecodeError("No JSON content", text or "", 0)

    # Primeiro: tentativa rápida por regex (rápida mas arriscada em casos grandes)
    try:
        # Use a raw-string regex to avoid invalid escape sequence warnings
        # and match the first JSON-like object. Kept as greedy per original
        # behaviour; fallback to brace-matching if this fails.
        m = re.search(r"({.*})", text, re.DOTALL)
        if m:
            candidate = m.group(1)
            # validar
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                # deixar cair para a estratégia mais robusta
                pass
    except Exception:
        # qualquer problema regex -> continuar para o próximo método
        pass

    # Segundo: extrator robusto por casamento de chaves
    candidate = _extract_json_from_text(text)
    if candidate:
        return candidate

    # Nenhuma estratégia encontrou JSON — levantar erro que será tratado pelo retry
    raise json.JSONDecodeError("No JSON found in provider response", text, 0)
