"""Política de retenção configurável e executor de expurgo.

Prazos em dias por classe de dado; ``None`` = nunca expurgar (trilha de auditoria: obrigação de
rastreabilidade, e ela só guarda dados mascarados). Os padrões abaixo são pontos de partida para
revisão do DPO/jurídico: prazos de guarda de documentos trabalhistas e fiscais variam por documento.
Configure por dicionário ou por um arquivo YAML (``RETENCAO_CONFIG``)::

    chat: 90
    documentos: 1825
    historico: 1825
    temporarios: 7
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

PADRAO: Dict[str, Optional[int]] = {
    "chat": 90,
    "documentos": 5 * 365,
    "historico": 5 * 365,
    "temporarios": 7,
    "consentimentos": 5 * 365,
    "auditoria": None,
}


class PoliticaInvalida(ValueError):
    pass


@dataclass(frozen=True)
class PoliticaDeRetencao:
    prazos: Dict[str, Optional[int]] = field(default_factory=lambda: dict(PADRAO))

    def __post_init__(self) -> None:
        for classe, dias in self.prazos.items():
            if dias is not None and (not isinstance(dias, int) or isinstance(dias, bool) or dias < 1):
                raise PoliticaInvalida(f"Prazo inválido para {classe!r}: {dias!r} (use um número inteiro de dias >= 1 ou null).")
        desconhecidas = set(self.prazos) - set(PADRAO)
        if desconhecidas:
            raise PoliticaInvalida(f"Classes desconhecidas: {sorted(desconhecidas)}. Válidas: {sorted(PADRAO)}.")

    @classmethod
    def carregar(cls, origem: Optional[Mapping[str, Any] | str | Path] = None, env: Optional[Mapping[str, str]] = None) -> "PoliticaDeRetencao":
        env = os.environ if env is None else env
        if origem is None:
            origem = env.get("RETENCAO_CONFIG")
        if origem is None:
            return cls()
        if isinstance(origem, (str, Path)):
            dados = yaml.safe_load(Path(origem).read_text(encoding="utf-8")) or {}
        else:
            dados = dict(origem)
        if "auditoria" in dados and dados["auditoria"] is not None:
            raise PoliticaInvalida("A trilha de auditoria não pode ter prazo de expurgo (deixe null).")
        return cls({**PADRAO, **dados})

    def prazo(self, classe: str) -> Optional[int]:
        return self.prazos[classe]

    def vencido(self, classe: str, idade_em_dias: float) -> bool:
        dias = self.prazo(classe)
        return dias is not None and idade_em_dias >= dias

    def para_dict(self) -> Dict[str, Optional[int]]:
        return dict(self.prazos)


def idade_em_dias(mtime: float, agora: Optional[float] = None) -> float:
    return ((agora if agora is not None else time.time()) - mtime) / 86400
