"""Cliente de LLM para conversa geral (Groq). O LLM nunca calcula valores: isso é do motor ``calc``."""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

Mensagens = List[Dict[str, str]]
LLM = Callable[[Mensagens], str]

MODELO_PADRAO = "llama-3.3-70b-versatile"


class LLMIndisponivel(Exception):
    """O provedor não respondeu (sem chave, rede, limite de uso ou erro do provedor)."""


class GroqLLM:
    def __init__(
        self,
        api_key: str,
        modelo: str = MODELO_PADRAO,
        tentativas: int = 3,
        timeout: float = 25.0,
        temperatura: float = 0.2,
        max_tokens: int = 700,
    ):
        if not api_key:
            raise LLMIndisponivel("GROQ_API_KEY não configurada.")
        try:
            from groq import Groq
        except Exception as exc:  # biblioteca ausente
            raise LLMIndisponivel("Biblioteca groq não instalada.") from exc
        self._cliente = Groq(api_key=api_key, timeout=timeout)
        self.modelo = modelo
        self.tentativas = max(1, tentativas)
        self.temperatura = temperatura
        self.max_tokens = max_tokens

    def __call__(self, mensagens: Mensagens) -> str:
        ultimo_erro: Optional[Exception] = None
        for tentativa in range(self.tentativas):
            try:
                resposta = self._cliente.chat.completions.create(
                    model=self.modelo,
                    messages=mensagens,
                    temperature=self.temperatura,
                    max_tokens=self.max_tokens,
                )
                texto = (resposta.choices[0].message.content or "").strip()
                if texto:
                    return texto
                ultimo_erro = LLMIndisponivel("Resposta vazia do provedor.")
            except Exception as exc:  # erros de rede, limite e API compartilham o mesmo tratamento
                ultimo_erro = exc
                logger.warning("Groq falhou (tentativa %d/%d): %s", tentativa + 1, self.tentativas, type(exc).__name__)
            time.sleep(min(2 ** tentativa, 8) * 0.5)
        raise LLMIndisponivel("O provedor de IA não respondeu.") from ultimo_erro


def llm_do_ambiente(env: Optional[dict] = None) -> Optional[LLM]:
    """LLM configurado por ``GROQ_API_KEY`` (e ``GROQ_MODEL``); ``None`` se não houver chave."""
    env = os.environ if env is None else env
    chave = env.get("GROQ_API_KEY", "").strip()
    if not chave:
        return None
    try:
        return GroqLLM(chave, env.get("GROQ_MODEL") or MODELO_PADRAO)
    except LLMIndisponivel:
        logger.warning("LLM não inicializado; o chat seguirá só com respostas determinísticas.")
        return None
