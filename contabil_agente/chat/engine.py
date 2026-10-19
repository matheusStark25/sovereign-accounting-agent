"""Motor de chat: cálculo determinístico primeiro, LLM só para conversa geral.

Fluxo de cada mensagem:

1. ``DialogoCalculo`` reconhece pedido de cálculo, junta os dados e chama ``contabil_agente.calc``.
2. Se não for cálculo e houver LLM, responde com o prompt da persona (Maria Helena, por padrão, ou MARCOS), com dados
   pessoais mascarados. Se quem chama passar ``ferramentas`` e o LLM souber usá-las, ela consulta o sistema de verdade
   (cálculo, tabelas, documentos da empresa, conciliação, validação) em vez de responder de memória.
3. Sem LLM ou com o provedor fora do ar, devolve uma resposta padrão honesta.

O estado da conversa é um dicionário JSON (``estado``), guardado por quem chama (ver ``ChatStore``).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from contabil_agente.core.prompts import obter_prompt
from contabil_agente.intelligence.dialogo_calculo import DialogoCalculo
from contabil_agente.lgpd.anonimizacao import PIIAnonymizer

from .ferramentas import Ferramentas, Pseudonimizador
from .llm import LLM, LLMIndisponivel
from .tom import escolher_variante

logger = logging.getLogger(__name__)

HISTORICO_MAXIMO = 40  # mensagens guardadas por conversa
CONTEXTO_LLM = 10  # mensagens enviadas ao LLM
TAMANHO_MAXIMO_MENSAGEM = 4000

MENSAGEM_SEM_LLM = (
    "Posso calcular rescisão, férias, 13º salário, INSS, IRRF, FGTS, folha, pró-labore, GPS, DAS do MEI e DARF em atraso. "
    "Diga o que precisa, por exemplo: “calcular rescisão, salário de R$ 3.000, admitido em 10/03/2023, "
    "demitido em 15/09/2026 sem justa causa”."
)
MENSAGEM_SEM_CONSENTIMENTO = (
    "A IA externa está desligada para esta empresa: falta o consentimento para enviar textos a provedores de IA (LGPD). "
    "Os cálculos funcionam normalmente: diga, por exemplo, “calcular férias com salário de R$ 3.000”."
)
MENSAGEM_LLM_FORA = (
    "Não consegui falar com a IA agora. Os cálculos continuam funcionando: diga, por exemplo, "
    "“calcular férias com salário de R$ 3.000”."
)


class ChatError(ValueError):
    """Mensagem inválida (vazia ou grande demais)."""


class ChatEngine:
    def __init__(self, llm: Optional[LLM] = None, hoje: Optional[date] = None, persona: str = "MARIA_HELENA", adaptar_tom: bool = True):
        self._llm = llm
        self._dialogo = DialogoCalculo(hoje=hoje)
        self._persona = persona.strip().upper().replace(" ", "_")
        self._prompt = obter_prompt(self._persona)
        self._adaptar_tom = adaptar_tom  # base, formal ou informal, pelo jeito de quem escreve

    @property
    def persona(self) -> str:
        return self._persona

    def responder(self, estado: Dict[str, Any], mensagem: str, usar_llm: bool = True, ferramentas: Optional[Ferramentas] = None) -> Dict[str, Any]:
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
            resultado = self._conversa_geral(historico, usar_llm, ferramentas)
            calculo = ferramentas.ultimo_calculo if ferramentas is not None else None
            if calculo and resultado.get("origem") == "llm":  # ela calculou pela ferramenta: a tela mostra o cartão e o PDF
                estado["ultimo_calculo"] = {"tipo": calculo["tipo"], "resultado": calculo["resultado"]}
                resultado.update(tipo=calculo["tipo"], dados_calculados=calculo["resultado"])
        historico.append({"role": "assistant", "content": resultado["resposta"]})
        del historico[:-HISTORICO_MAXIMO]
        return resultado

    def _conversa_geral(self, historico: List[Dict[str, str]], usar_llm: bool = True, ferramentas: Optional[Ferramentas] = None) -> Dict[str, Any]:
        if self._llm is not None and not usar_llm:
            return {"resposta": MENSAGEM_SEM_CONSENTIMENTO, "status": "ok", "origem": "padrao"}
        if self._llm is None:
            return {"resposta": MENSAGEM_SEM_LLM, "status": "ok", "origem": "padrao"}
        tom = escolher_variante(m["content"] for m in historico if m["role"] == "user") if self._adaptar_tom else "base"
        mensagens = [{"role": "system", "content": obter_prompt(self._persona, tom) if self._adaptar_tom else self._prompt}]
        com_ferramentas = ferramentas is not None and hasattr(self._llm, "com_ferramentas")
        pseudo = Pseudonimizador()
        for m in historico[-CONTEXTO_LLM:]:
            texto = pseudo.ocultar(m["content"]) if com_ferramentas else m["content"]
            mensagens.append({"role": m["role"], "content": PIIAnonymizer.anonymize_text(texto)})
        try:
            if com_ferramentas:
                def executar(nome: str, argumentos: Dict[str, Any]) -> Dict[str, Any]:
                    # a ferramenta recebe os valores reais (só nesta requisição); o LLM recebe o resultado de novo mascarado
                    return pseudo.ocultar_valor(ferramentas.executar(nome, pseudo.revelar_valor(argumentos)))

                texto, chamadas = self._llm.com_ferramentas(mensagens, ferramentas.esquemas, executar)
                if not texto:
                    raise LLMIndisponivel("Resposta vazia do provedor.")
                return {"resposta": pseudo.revelar(texto), "status": "ok", "origem": "llm", "persona": self._persona, "tom": tom,
                        "ferramentas": chamadas}
            return {"resposta": self._llm(mensagens), "status": "ok", "origem": "llm", "persona": self._persona, "tom": tom}
        except LLMIndisponivel:
            return {"resposta": MENSAGEM_LLM_FORA, "status": "ok", "origem": "padrao"}
        except Exception:
            logger.exception("Falha inesperada no LLM")
            return {"resposta": MENSAGEM_LLM_FORA, "status": "ok", "origem": "padrao"}
