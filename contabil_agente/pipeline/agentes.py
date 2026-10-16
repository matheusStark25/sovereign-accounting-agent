"""Agentes do pipeline: Worker (processa), Revisor (valida) e Corretor (corrige).

Cada agente tem um modo determinístico (sempre disponível) e usa um provedor de LLM quando houver.
Os papéis do README: o Worker é o "DeepSeek Worker" (persona MARCOS), o Revisor é o "Gemini Reviewer"
e o Corretor ocupa o lugar do "Copilot Coder": o GitHub Copilot não tem API para chamar de dentro de um
sistema, então a correção é feita por regras (evidência no texto) e, opcionalmente, por qualquer LLM.

Princípio central: o LLM sugere, o texto do documento decide. Nenhum valor sugerido entra no resultado se
não aparece no documento (``pipeline.evidencia``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from contabil_agente.core.prompts import obter_prompt
from contabil_agente.documentos.tipos import Alerta

from .evidencia import valor_aparece
from .provedores import ProvedorIndisponivel

logger = logging.getLogger(__name__)

ISENTOS_DE_EVIDENCIA = {"blocos", "total_registros", "codigo_evento", "evento", "valores", "chave_acesso"}


class Provedor(Protocol):
    nome: str

    def gerar_json(self, sistema: str, usuario: str) -> Dict[str, Any]: ...


# ------------------------------------------------------------------------------- Worker
@dataclass
class SaidaWorker:
    origem: str  # deterministico | llm
    resumo: str
    sugestoes: Dict[str, Any] = field(default_factory=dict)
    erro: Optional[str] = None


class AgenteWorker:
    """Processa o documento: resume e sugere campos extras (só sugere; quem aceita é o Corretor)."""

    def __init__(self, provedor: Optional[Provedor] = None, persona: str = "MARCOS"):
        self.provedor = provedor
        self._sistema = (
            obter_prompt(persona)
            + "\n\nTAREFA: você recebe o texto de um documento contábil/trabalhista brasileiro (com dados pessoais já "
            "mascarados), o tipo e os campos já extraídos. Responda SOMENTE um JSON com: "
            '"resumo" (até 3 frases, em português) e "campos_adicionais" (objeto nome->valor, apenas valores que '
            "aparecem literalmente no texto; não calcule nem invente)."
        )

    def processar(self, texto: str, tipo: str, dados: Dict[str, Any], resumo_base: str) -> SaidaWorker:
        if self.provedor is None:
            return SaidaWorker("deterministico", resumo_base)
        try:
            resposta = self.provedor.gerar_json(
                self._sistema, json.dumps({"tipo": tipo, "campos_extraidos": dados, "texto": texto}, ensure_ascii=False)
            )
        except ProvedorIndisponivel as exc:
            return SaidaWorker("deterministico", resumo_base, erro=str(exc))
        extras = resposta.get("campos_adicionais")
        resumo = resposta.get("resumo")
        return SaidaWorker(
            "llm",
            resumo if isinstance(resumo, str) and resumo.strip() else resumo_base,
            {str(k): v for k, v in extras.items()} if isinstance(extras, dict) else {},
        )


# ------------------------------------------------------------------------------ Revisor
@dataclass(frozen=True)
class Divergencia:
    campo: str
    motivo: str
    valor_atual: Any = None
    valor_proposto: Any = None
    origem: str = "deterministico"

    def to_dict(self) -> Dict[str, Any]:
        return {"campo": self.campo, "motivo": self.motivo, "valor_atual": self.valor_atual,
                "valor_proposto": self.valor_proposto, "origem": self.origem}


@dataclass
class SaidaRevisao:
    origem: str
    concorda: bool
    divergencias: List[Divergencia] = field(default_factory=list)
    erro: Optional[str] = None


class AgenteRevisor:
    """Confere o resultado contra o documento: primeiro por evidência (sempre), depois por LLM (se houver)."""

    def __init__(self, provedor: Optional[Provedor] = None):
        self.provedor = provedor
        self._sistema = (
            "Você é um revisor de documentos contábeis e trabalhistas brasileiros. Receba o texto do documento "
            "(dados pessoais mascarados), os campos extraídos e os alertas. Procure campos extraídos que contradigam o "
            'texto. Responda SOMENTE um JSON: {"concorda": true|false, "divergencias": [{"campo": "...", '
            '"valor_proposto": "...", "motivo": "..."}]}. Proponha valor apenas se ele aparece literalmente no texto.'
        )

    def revisar(self, texto: str, tipo: str, dados: Dict[str, Any], alertas: List[Alerta], formato: str) -> SaidaRevisao:
        divergencias: List[Divergencia] = []
        for campo, valor in dados.items():
            if campo in ISENTOS_DE_EVIDENCIA or isinstance(valor, (dict, list)):
                continue
            if not valor_aparece(texto, valor):
                divergencias.append(Divergencia(campo, "O valor não aparece no texto do documento.", valor_atual=valor))
        origem, erro = "deterministico", None
        if self.provedor is not None:
            try:
                resposta = self.provedor.gerar_json(
                    self._sistema,
                    json.dumps({"tipo": tipo, "campos_extraidos": dados, "alertas": [a.to_dict() for a in alertas], "texto": texto}, ensure_ascii=False),
                )
                origem = "llm"
                for item in resposta.get("divergencias") or []:
                    if isinstance(item, dict) and item.get("campo"):
                        proposto = item.get("valor_proposto")
                        if proposto is not None and str(proposto) == str(dados.get(str(item["campo"]))):
                            continue  # o valor atual já é o proposto: a divergência está resolvida
                        divergencias.append(Divergencia(
                            str(item["campo"]), str(item.get("motivo", "")), dados.get(str(item["campo"])),
                            item.get("valor_proposto"), origem="llm",
                        ))
            except ProvedorIndisponivel as exc:
                erro = str(exc)
        return SaidaRevisao(origem, not divergencias, divergencias, erro)


# ------------------------------------------------------------------------------ Corretor
@dataclass(frozen=True)
class Correcao:
    campo: str
    antes: Any
    depois: Any
    motivo: str

    def to_dict(self) -> Dict[str, Any]:
        return {"campo": self.campo, "antes": self.antes, "depois": self.depois, "motivo": self.motivo}


@dataclass
class SaidaCorrecao:
    dados: Dict[str, Any]
    aplicadas: List[Correcao] = field(default_factory=list)
    rejeitadas: List[Dict[str, Any]] = field(default_factory=list)


class AgenteCorretor:
    """Aplica correções com regra de evidência; o que não tem evidência é rejeitado ou removido."""

    def corrigir(
        self, texto: str, dados: Dict[str, Any], divergencias: List[Divergencia], sugestoes_worker: Optional[Dict[str, Any]] = None
    ) -> SaidaCorrecao:
        novos = dict(dados)
        aplicadas: List[Correcao] = []
        rejeitadas: List[Dict[str, Any]] = []
        for d in divergencias:
            if d.valor_proposto is not None and str(d.valor_proposto).strip() != "":
                if valor_aparece(texto, d.valor_proposto):
                    aplicadas.append(Correcao(d.campo, novos.get(d.campo), d.valor_proposto, f"valor proposto confirmado no texto ({d.origem})"))
                    novos[d.campo] = d.valor_proposto
                else:
                    rejeitadas.append({**d.to_dict(), "rejeitada_porque": "o valor proposto não aparece no documento"})
            elif d.campo in novos and d.motivo.startswith("O valor não aparece"):
                aplicadas.append(Correcao(d.campo, novos[d.campo], None, "removido: sem evidência no texto"))
                del novos[d.campo]
        for campo, valor in (sugestoes_worker or {}).items():
            if campo in novos or isinstance(valor, (dict, list)):
                continue
            if valor_aparece(texto, valor):
                aplicadas.append(Correcao(campo, None, valor, "sugestão do worker confirmada no texto"))
                novos[campo] = valor
            else:
                rejeitadas.append({"campo": campo, "valor_proposto": valor, "origem": "llm", "rejeitada_porque": "a sugestão do worker não aparece no documento"})
        return SaidaCorrecao(novos, aplicadas, rejeitadas)
