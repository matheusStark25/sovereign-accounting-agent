"""Processamento de documentos em lote (Celery): cada arquivo passa pelo pipeline de 7 estados."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from contabil_agente.documentos.leitura import ArquivoInvalido

from . import celery_app
from .contexto import obter_contexto

LIMITE_DO_LOTE = 200


def nome_simples(nome: str) -> bool:
    """Só nome de arquivo, sem pasta: recusa barra e barra invertida em qualquer sistema (no Linux um nome com barra
    invertida seria um nome comum, e o comportamento não pode mudar de um sistema para outro)."""
    return bool(nome) and nome not in (".", "..") and not any(c in nome for c in ("/", "\\", "\0")) and os.path.basename(nome) == nome


def _dentro_de(base: Path, alvo: Path) -> bool:
    try:
        alvo.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


@celery_app.task(name="documentos.processar_lote")
def processar_lote(job_id: str, tenant: str, ator: str, pasta_de_entrada: str, nomes: List[str]) -> Dict[str, Any]:
    """Processa ``nomes`` (arquivos dentro de ``pasta_de_entrada``). Nome com caminho fora da pasta é recusado."""
    from contabil_agente.rpa import estado as st

    ctx = obter_contexto()
    ctx.status.atualizar(job_id, st.EXECUTANDO, f"Processando {len(nomes)} arquivo(s).")
    base = Path(pasta_de_entrada)
    if len(nomes) > LIMITE_DO_LOTE:
        raise ValueError(f"Lote maior que {LIMITE_DO_LOTE} arquivos.")
    usar_ia = ctx.lgpd.pode_tratar("envio_a_provedor_de_ia", tenant)
    itens: List[Dict[str, Any]] = []
    for nome in nomes:
        caminho = base / nome
        if not nome_simples(nome) or not _dentro_de(base, caminho):
            itens.append({"arquivo": nome, "status": "recusado", "motivo": "nome de arquivo inválido"})
            continue
        try:
            r = ctx.dispatcher.process(document_path=str(caminho), tenant=tenant, ator=ator, usar_ia=usar_ia)
        except ArquivoInvalido as exc:
            itens.append({"arquivo": nome, "status": "invalido", "motivo": str(exc)})
            continue
        itens.append({
            "arquivo": nome, "status": "arquivado" if not r.falha else "falhou", "tipo": r.tipo, "estado": r.estado,
            "alertas": [a.codigo for a in r.alertas], "requer_revisao": r.requer_revisao, "audit_trail_id": r.audit_trail_id,
        })
    resumo = {s: sum(1 for i in itens if i["status"] == s) for s in ("arquivado", "falhou", "invalido", "recusado")}
    saida = {"total": len(itens), "resumo": resumo, "itens": itens}
    ctx.status.atualizar(job_id, st.CONCLUIDO, f"{resumo['arquivado']} de {len(itens)} arquivado(s).", saida)
    return saida
