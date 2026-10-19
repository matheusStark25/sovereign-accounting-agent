"""Cliente de LLM para conversa geral (Groq). O LLM nunca calcula valores: isso é do motor ``calc``."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

Mensagens = List[Dict[str, str]]
LLM = Callable[[Mensagens], str]

# O llama-3.3-70b-versatile foi desligado pela Groq em 2026-08-16; este é o substituto indicado na documentação oficial
# (conferido em 2026-10-17). Sobrescreva por GROQ_MODEL e confira com: python -m agente_v2.cli verificar-ia
MODELO_PADRAO = "openai/gpt-oss-120b"


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
        max_tokens: int = 2000,  # modelos de raciocínio gastam parte disso antes de responder
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

    def listar_modelos(self) -> List[str]:
        return [m.id for m in self._cliente.models.list().data]

    def verificar(self) -> Dict[str, object]:
        """Confere de verdade com a Groq: a chave vale, o modelo existe e uma conversa mínima volta com texto."""
        res: Dict[str, object] = {"provedor": "groq", "modelo": self.modelo, "chave_valida": False, "modelo_existe": False, "chamada_ok": False}
        try:
            modelos = self.listar_modelos()
            res["chave_valida"] = True
            res["modelo_existe"] = self.modelo in modelos
            if not res["modelo_existe"]:
                res["erro"] = f"O modelo {self.modelo!r} não está na lista da Groq."
                res["alternativas"] = sorted(modelos)[:12]
                return res
            res["chamada_ok"] = bool(self([{"role": "user", "content": "Responda apenas com a palavra OK."}]))
        except Exception as exc:  # noqa: BLE001 - o diagnóstico nunca levanta; devolve o motivo
            res["erro"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return res

    def _criar(self, mensagens: List[Dict[str, Any]], ferramentas: Optional[List[Dict[str, Any]]] = None):
        """Uma resposta do modelo (com novas tentativas). Sem ferramentas, só aceita resposta com texto."""
        ultimo_erro: Optional[Exception] = None
        extra = {"tools": ferramentas, "tool_choice": "auto"} if ferramentas else {}
        for tentativa in range(self.tentativas):
            try:
                resposta = self._cliente.chat.completions.create(
                    model=self.modelo, messages=mensagens, temperature=self.temperatura, max_tokens=self.max_tokens, **extra,
                )
                msg = resposta.choices[0].message
                if (msg.content or "").strip() or getattr(msg, "tool_calls", None):
                    return msg
                ultimo_erro = LLMIndisponivel("Resposta vazia do provedor.")
            except Exception as exc:  # erros de rede, limite e API compartilham o mesmo tratamento
                ultimo_erro = exc
                logger.warning("Groq falhou (tentativa %d/%d): %s", tentativa + 1, self.tentativas, type(exc).__name__)
            time.sleep(min(2 ** tentativa, 8) * 0.5)
        raise LLMIndisponivel("O provedor de IA não respondeu.") from ultimo_erro

    def __call__(self, mensagens: Mensagens) -> str:
        return (self._criar(mensagens).content or "").strip()

    def com_ferramentas(
        self, mensagens: Mensagens, ferramentas: List[Dict[str, Any]], executar: Callable[[str, Dict[str, Any]], Dict[str, Any]],
        max_rodadas: int = 5,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Conversa em que o modelo pode chamar ferramentas do sistema. Devolve o texto final e as chamadas feitas."""
        conversa: List[Dict[str, Any]] = list(mensagens)
        chamadas: List[Dict[str, Any]] = []
        for _ in range(max_rodadas):
            msg = self._criar(conversa, ferramentas)
            pedidos = getattr(msg, "tool_calls", None) or []
            if not pedidos:
                return (msg.content or "").strip(), chamadas
            conversa.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": p.id, "type": "function", "function": {"name": p.function.name, "arguments": p.function.arguments or "{}"}} for p in pedidos]})
            for p in pedidos:
                try:
                    argumentos = json.loads(p.function.arguments or "{}")
                except ValueError:
                    argumentos = None
                if isinstance(argumentos, dict):
                    resultado = executar(p.function.name, argumentos)
                else:
                    resultado = {"status": "erro", "mensagem": "Os argumentos não são um objeto JSON válido."}
                chamadas.append({"ferramenta": p.function.name, "status": resultado.get("status")})
                conteudo = json.dumps(resultado, ensure_ascii=False, default=str, separators=(",", ":"))
                conversa.append({"role": "tool", "tool_call_id": p.id, "content": conteudo[:12000]})
        conversa.append({"role": "user", "content": "Responda agora com o que já tem, sem chamar mais ferramentas."})
        return (self._criar(conversa).content or "").strip(), chamadas


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
