"""Dependências das tarefas (auditoria, dispatcher, LGPD, status, chaves), montadas uma vez por processo."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from contabil_agente.lgpd import ConsentimentoStore, PoliticaDeRetencao, ServicoLGPD
from contabil_agente.pipeline import ArquivoDestino, DocumentDispatcher, HistoricoDocumentos, provedores_do_ambiente
from contabil_agente.rpa import ConfigPortalFGTS
from contabil_agente.rpa.estado import StatusStore
from contabil_agente.security.worm_audit import WormAudit


@dataclass
class Contexto:
    audit: WormAudit
    dispatcher: DocumentDispatcher
    lgpd: ServicoLGPD
    status: StatusStore
    config_fgts: ConfigPortalFGTS
    pasta_de_trabalho: Path
    chave_privada_rpa: Optional[Dict[str, str]]
    chave_hash: str
    # só para testes: age sobre a página quando o robô pausa (faz o papel da pessoa)
    ao_pausar: Optional[Callable[[str, str, Any], None]] = None


_CONTEXTO: Optional[Contexto] = None


def definir_contexto(ctx: Optional[Contexto]) -> None:
    global _CONTEXTO
    _CONTEXTO = ctx


def _json_do_ambiente(env: Mapping[str, str], nome: str) -> Optional[Dict[str, str]]:
    bruto = env.get(nome)
    return json.loads(bruto) if bruto else None


def contexto_do_ambiente(env: Optional[Mapping[str, str]] = None) -> Contexto:
    """Monta o contexto a partir do ambiente (e do Vault, se configurado), como a API faz."""
    from agente_v2.config import settings
    from agente_v2.vault_client import VaultClient, carregar_segredos

    segredos = carregar_segredos(VaultClient.do_ambiente(env), env)
    base = settings.DATA_DIR
    audit = WormAudit.do_ambiente(settings.AUDIT_DIR, segredos)
    prov = provedores_do_ambiente(segredos)
    historico = HistoricoDocumentos(base / "documentos.db")
    dispatcher = DocumentDispatcher(audit, historico, worker_llm=prov["worker"], revisor_llm=prov["revisor"], destinos=[ArquivoDestino(base / "arquivo")])
    chave_hash = segredos.get("PII_HASH_KEY") or segredos.get("JWT_SECRET", "")
    lgpd = ServicoLGPD(audit, ConsentimentoStore(base / "lgpd.db", chave_hash), PoliticaDeRetencao.carregar(), raiz_arquivo=base / "arquivo", historico=historico)
    return Contexto(
        audit=audit, dispatcher=dispatcher, lgpd=lgpd, status=StatusStore(base / "rpa.db"),
        config_fgts=ConfigPortalFGTS.carregar(env=segredos), pasta_de_trabalho=base / "rpa",
        chave_privada_rpa=_json_do_ambiente(segredos, "RPA_PQC_PRIVATE_KEY"), chave_hash=chave_hash,
    )


def obter_contexto() -> Contexto:
    global _CONTEXTO
    if _CONTEXTO is None:
        _CONTEXTO = contexto_do_ambiente()
    return _CONTEXTO
