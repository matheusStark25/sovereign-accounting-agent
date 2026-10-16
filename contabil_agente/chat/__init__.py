"""Chat do agente: motor (cálculo + LLM), cliente de LLM e armazenamento de conversas."""

from .engine import ChatEngine, ChatError
from .llm import LLMIndisponivel, llm_do_ambiente
from .store import ChatStore

__all__ = ["ChatEngine", "ChatError", "ChatStore", "LLMIndisponivel", "llm_do_ambiente"]
