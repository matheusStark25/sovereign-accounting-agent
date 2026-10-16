"""Classifica, extrai e confere um documento (sem agentes de IA): a base determinística do pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .leitura import Conteudo, ler_documento
from .tipos import TIPOS, Alerta, TipoDocumento, corpus

SCORE_MINIMO = 3
ALIASES = {
    "SPED": None,  # ambíguo: classifica entre os tipos SPED
    "ESOCIAL": "ESOCIAL_XML", "E-SOCIAL": "ESOCIAL_XML", "REINF": "EFD_REINF", "EFD-REINF": "EFD_REINF",
    "NFE": "NFE_XML", "NF-E": "NFE_XML", "PERDCOMP": "PER_DCOMP", "PER/DCOMP": "PER_DCOMP",
    "SEFIP": "GFIP", "CONTRACHEQUE": "HOLERITE", "EFD_CONTRIBUICOES": "EFD_CONTRIBUICOES",
    "EFD-CONTRIBUICOES": "EFD_CONTRIBUICOES", "EFD": "EFD_ICMS_IPI", "FGTS": "FGTS_GUIA",
}


class TipoDesconhecido(ValueError):
    pass


@dataclass
class ResultadoDocumento:
    tipo: Optional[str]
    nome_tipo: Optional[str]
    confianca: float
    candidatos: List[Dict[str, Any]]
    extracted_data: Dict[str, Any]
    calculations: Dict[str, Any]
    alertas: List[Alerta]
    avisos: List[str]
    faltando: List[str]
    formato: str
    sha256: str
    paginas: int = 0
    audit_trail_id: Optional[str] = None
    estado: str = "PROCESSING"
    resumo: str = ""
    etapas: List[Dict[str, Any]] = field(default_factory=list)
    falha: Optional[str] = None
    requer_revisao: bool = False
    agentes: Dict[str, str] = field(default_factory=dict)
    divergencias: List[Dict[str, Any]] = field(default_factory=list)
    correcoes: List[Dict[str, Any]] = field(default_factory=list)
    rejeitadas: List[Dict[str, Any]] = field(default_factory=list)
    destinos: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def tem_erro(self) -> bool:
        return any(a.severidade == "erro" for a in self.alertas)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tipo": self.tipo,
            "nome_tipo": self.nome_tipo,
            "confianca": self.confianca,
            "candidatos": self.candidatos,
            "extracted_data": self.extracted_data,
            "calculations": self.calculations,
            "alertas": [a.to_dict() for a in self.alertas],
            "avisos": self.avisos,
            "faltando": self.faltando,
            "formato": self.formato,
            "sha256": self.sha256,
            "paginas": self.paginas,
            "audit_trail_id": self.audit_trail_id,
            "estado": self.estado,
            "resumo": self.resumo,
            "etapas": self.etapas,
            "falha": self.falha,
            "requer_revisao": self.requer_revisao,
            "agentes": self.agentes,
            "divergencias": self.divergencias,
            "correcoes": self.correcoes,
            "rejeitadas": self.rejeitadas,
            "destinos": self.destinos,
        }


@lru_cache(maxsize=None)
def _regex(padrao: str) -> "re.Pattern[str]":
    return re.compile(padrao, re.IGNORECASE)


def pontuar(conteudo: Conteudo) -> List[Tuple[str, int]]:
    texto = corpus(conteudo)
    notas: List[Tuple[str, int]] = []
    for codigo, tipo in TIPOS.items():
        nota = sum(peso for padrao, peso in tipo.assinaturas if _regex(padrao).search(texto))
        if nota:
            notas.append((codigo, nota))
    return sorted(notas, key=lambda x: (-x[1], x[0]))


def classificar(conteudo: Conteudo, restrito_a: Optional[List[str]] = None) -> Tuple[Optional[str], float, List[Dict[str, Any]]]:
    notas = [(c, n) for c, n in pontuar(conteudo) if restrito_a is None or c in restrito_a]
    candidatos = [{"tipo": c, "pontos": n, "confianca": round(min(1.0, n / TIPOS[c].peso_maximo), 2)} for c, n in notas[:5]]
    if not notas or notas[0][1] < SCORE_MINIMO:
        return None, 0.0, candidatos
    melhor, nota = notas[0]
    confianca = min(1.0, nota / TIPOS[melhor].peso_maximo)
    if len(notas) > 1 and notas[1][1] == nota:
        confianca *= 0.6  # empate: o documento não é conclusivo
    return melhor, round(confianca, 2), candidatos


def resolver_tipo_informado(tipo: str) -> Optional[str]:
    """Código do registro, apelido (ex.: ESOCIAL) ou ``None`` quando é um grupo (SPED)."""
    chave = (tipo or "").strip().upper().replace(" ", "_")
    if chave in ALIASES:
        return ALIASES[chave]
    if chave in TIPOS:
        return chave
    raise TipoDesconhecido(f"Tipo de documento desconhecido: {tipo!r}. Use um de: {', '.join(sorted(TIPOS))}.")


def _resumo(tipo: Optional[TipoDocumento], dados: Dict[str, Any], alertas: List[Alerta], faltando: List[str]) -> str:
    if tipo is None:
        return "Não consegui identificar o tipo do documento."
    partes = [f"{tipo.nome}: {len(dados)} campo(s) extraído(s)"]
    if faltando:
        partes.append(f"não encontrei: {', '.join(faltando)}")
    erros = [a for a in alertas if a.severidade == "erro"]
    avisos = [a for a in alertas if a.severidade == "aviso"]
    if erros:
        partes.append(f"{len(erros)} erro(s) de conferência")
    if avisos:
        partes.append(f"{len(avisos)} aviso(s)")
    if not erros and not avisos:
        partes.append("nenhuma divergência encontrada")
    return "; ".join(partes) + "."


def processar_conteudo(conteudo: Conteudo, tipo_informado: Optional[str] = None) -> ResultadoDocumento:
    alertas: List[Alerta] = []
    codigo: Optional[str]
    restrito: Optional[List[str]] = None
    informado: Optional[str] = None
    if tipo_informado:
        informado = resolver_tipo_informado(tipo_informado)
        if informado is None:
            restrito = [c for c, t in TIPOS.items() if t.categoria == "sped"]

    if informado is not None:
        codigo = informado
        sugerido, conf_sug, candidatos = classificar(conteudo)
        pontos = dict((c, n) for c, n in pontuar(conteudo)).get(informado, 0)
        confianca = round(min(1.0, pontos / TIPOS[informado].peso_maximo), 2)
        if pontos < SCORE_MINIMO:
            alertas.append(Alerta("tipo_nao_confirmado", f"O conteúdo não confirma o tipo informado ({informado}).", "aviso"))
        if sugerido and sugerido != informado and conf_sug >= 0.5 and pontos < SCORE_MINIMO:
            alertas.append(Alerta("tipo_informado_diverge", f"O conteúdo parece ser {sugerido}, não {informado}.", "aviso"))
    else:
        codigo, confianca, candidatos = classificar(conteudo, restrito)

    avisos = list(conteudo.avisos)
    if codigo is None:
        return ResultadoDocumento(None, None, 0.0, candidatos, {}, {}, alertas, avisos, [], conteudo.formato,
                                  conteudo.sha256, conteudo.paginas, resumo=_resumo(None, {}, alertas, []))

    tipo = TIPOS[codigo]
    dados = tipo.extrair(conteudo)
    faltando = [c for c in tipo.esperados if c not in dados]
    calculos: Dict[str, Any] = {}
    if tipo.conferir is not None:
        extras, calculos = tipo.conferir(dados, conteudo)
        alertas.extend(extras)
    if tipo.observacao:
        avisos.append(tipo.observacao)
    return ResultadoDocumento(
        codigo, tipo.nome, confianca, candidatos, dados, calculos, alertas, avisos, faltando,
        conteudo.formato, conteudo.sha256, conteudo.paginas, resumo=_resumo(tipo, dados, alertas, faltando),
    )


def processar_documento(origem: Union[str, Path, bytes], tipo: Optional[str] = None, nome: Optional[str] = None) -> ResultadoDocumento:
    return processar_conteudo(ler_documento(origem, nome), tipo)
