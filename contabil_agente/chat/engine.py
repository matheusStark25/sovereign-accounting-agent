"""Motor de chat: cálculo determinístico primeiro, LLM só para conversa geral.

Fluxo de cada mensagem:

1. ``DialogoCalculo`` reconhece pedido de cálculo, junta os dados e chama ``contabil_agente.calc``.
2. Se não for cálculo e houver LLM, responde com o prompt da persona (MARCOS ou Maria Helena), com dados pessoais mascarados.
3. Sem LLM ou com o provedor fora do ar, devolve uma resposta padrão honesta.

O estado da conversa é um dicionário JSON (``estado``), guardado por quem chama (ver ``ChatStore``).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from contabil_agente.core.prompts import obter_prompt
from contabil_agente.intelligence.dialogo_calculo import DialogoCalculo
from contabil_agente.middleware.lgpd import PIIAnonymizer

from .llm import LLM, LLMIndisponivel

logger = logging.getLogger(__name__)

HISTORICO_MAXIMO = 40  # mensagens guardadas por conversa
CONTEXTO_LLM = 10  # mensagens enviadas ao LLM
TAMANHO_MAXIMO_MENSAGEM = 4000

MENSAGEM_SEM_LLM = (
    "Posso calcular rescisão, férias, 13º salário, INSS, IRRF, FGTS e folha. "
    "Diga o que precisa, por exemplo: “calcular rescisão, salário de R$ 3.000, admitido em 10/03/2023, "
    "demitido em 15/09/2026 sem justa causa”."
)
MENSAGEM_LLM_FORA = (
    "Não consegui falar com a IA agora. Os cálculos continuam funcionando: diga, por exemplo, "
    "“calcular férias com salário de R$ 3.000”."
)


class ChatError(ValueError):
    """Mensagem inválida (vazia ou grande demais)."""


class ChatEngine:
    def __init__(self, llm: Optional[LLM] = None, hoje: Optional[date] = None, persona: str = "MARCOS"):
        self._llm = llm
        self._dialogo = DialogoCalculo(hoje=hoje)
        self._prompt = obter_prompt(persona)

    def responder(self, estado: Dict[str, Any], mensagem: str) -> Dict[str, Any]:
        """Atualiza ``estado`` e devolve ``{resposta, status, tipo, dados_calculados}``."""
        texto = (mensagem or "").strip()
        if not texto:
            raise ChatError("Mensagem vazia.")
        if len(texto) > TAMANHO_MAXIMO_MENSAGEM:
            raise ChatError(f"Mensagem grande demais (máximo {TAMANHO_MAXIMO_MENSAGEM} caracteres).")

        historico: List[Dict[str, str]] = estado.setdefault("mensagens", [])
        historico.append({"role": "user", "content": texto})

        resultado = self._dialogo.processar(estado, texto)
        if resultado is None:
            resultado = self._conversa_geral(historico)
        historico.append({"role": "assistant", "content": resultado["resposta"]})
        del historico[:-HISTORICO_MAXIMO]
        return resultado

    def _conversa_geral(self, historico: List[Dict[str, str]]) -> Dict[str, Any]:
        if self._llm is None:
            return {"resposta": MENSAGEM_SEM_LLM, "status": "ok", "origem": "padrao"}
        mensagens = [{"role": "system", "content": self._prompt}]
        for m in historico[-CONTEXTO_LLM:]:
            mensagens.append({"role": m["role"], "content": PIIAnonymizer.anonymize_text(m["content"])})
        try:
            return {"resposta": self._llm(mensagens), "status": "ok", "origem": "llm"}
        except LLMIndisponivel:
            return {"resposta": MENSAGEM_LLM_FORA, "status": "ok", "origem": "padrao"}
        except Exception:
            logger.exception("Falha inesperada no LLM")
            return {"resposta": MENSAGEM_LLM_FORA, "status": "ok", "origem": "padrao"}
