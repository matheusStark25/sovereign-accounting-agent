"""Tarefa do extrato do FGTS: decifra o CPF, roda o robô (com pausa para a pessoa), processa o PDF no pipeline."""

from __future__ import annotations

import logging
from typing import Any, Dict

from contabil_agente.lgpd import TratamentoSemBaseLegal
from contabil_agente.lgpd.anonimizacao import PIIAnonymizer
from contabil_agente.resilience import CircuitoAberto
from contabil_agente.rpa import ErroDoRobo, HumanoNaoRespondeu, PortalBloqueouAutomacao, RoboExtratoFGTS
from contabil_agente.rpa import estado as st
from contabil_agente.security import pqc

from . import celery_app
from .contexto import obter_contexto

logger = logging.getLogger(__name__)


def _aad(tenant: str, job_id: str) -> bytes:
    return f"rpa-fgts|{tenant}|{job_id}".encode("utf-8")


def envelope_do_cpf(chave_publica: Dict[str, str], cpf: str, tenant: str, job_id: str) -> Dict[str, str]:
    """Cifra o CPF para o worker (ML-KEM-768 + X25519 + AES-GCM) antes de ir para o broker."""
    return pqc.cifrar_hibrido(chave_publica, cpf.encode("utf-8"), _aad(tenant, job_id))


def abrir_cpf(chave_privada: Dict[str, str], envelope: Dict[str, str], tenant: str, job_id: str) -> str:
    return pqc.decifrar_hibrido(chave_privada, envelope, _aad(tenant, job_id)).decode("utf-8")


@celery_app.task(name="rpa.extrato_fgts", bind=True, max_retries=0)
def extrato_fgts(self, job_id: str, tenant: str, ator: str, envelope: Dict[str, str]) -> Dict[str, Any]:
    ctx = obter_contexto()
    status = ctx.status

    def falhar(mensagem: str) -> Dict[str, Any]:
        status.atualizar(job_id, st.FALHOU, mensagem)
        ctx.audit.append("rpa.fgts.job_falhou", {"job": job_id, "motivo": mensagem}, tenant=tenant, ator=ator)
        return {"status": "falhou", "mensagem": mensagem}

    if ctx.chave_privada_rpa is None:
        return falhar("Chave privada do RPA (RPA_PQC_PRIVATE_KEY) não configurada neste worker.")
    try:
        cpf = abrir_cpf(ctx.chave_privada_rpa, envelope, tenant, job_id)
    except pqc.PQCError:
        return falhar("Não consegui decifrar o CPF: envelope adulterado ou chave errada.")
    try:
        ctx.lgpd.exigir_base_legal("consulta_extrato_fgts", tenant, cpf)  # revalida no worker: o consentimento pode ter sido revogado
    except TratamentoSemBaseLegal as exc:
        return falhar(str(exc))

    status.atualizar(job_id, st.EXECUTANDO, "Abrindo o portal do FGTS.")

    def notificar(motivo: str, seletor: str, page: Any) -> None:
        status.atualizar(job_id, st.AGUARDANDO_HUMANO, f"Resolva na janela do navegador: {motivo}.")
        if ctx.ao_pausar is not None:
            ctx.ao_pausar(motivo, seletor, page)

    robo = RoboExtratoFGTS(
        ctx.config_fgts, ctx.pasta_de_trabalho / job_id, ctx.audit, tenant=tenant, ator=ator, notificar_humano=notificar, chave_hash=ctx.chave_hash,
    )
    try:
        extrato = robo.executar(cpf)
    except HumanoNaoRespondeu:
        return falhar("Ninguém resolveu o captcha/login a tempo.")
    except CircuitoAberto as exc:
        return falhar(f"Portal temporariamente suspenso após falhas seguidas: {exc}")
    except PortalBloqueouAutomacao:
        return falhar("O portal bloqueou o navegador automatizado. Baixe o extrato no seu navegador normal e envie o PDF pelo sistema (POST /api/v1/documentos).")
    except ErroDoRobo as exc:
        return falhar(f"Robô: {exc.motivo}")

    usar_ia = ctx.lgpd.pode_tratar("envio_a_provedor_de_ia", tenant)
    doc = ctx.dispatcher.process(document_path=extrato.caminho, document_type="FGTS_EXTRATO", tenant=tenant, ator=ator, usar_ia=usar_ia)
    resultado = {
        "sha256": extrato.sha256,
        "tipo": doc.tipo,
        "estado": doc.estado,
        "audit_trail_id": doc.audit_trail_id,
        "alertas": [a.codigo for a in doc.alertas],
        "requer_revisao": doc.requer_revisao,
        "titular": PIIAnonymizer.hash_pii(cpf, ctx.chave_hash),
    }
    if doc.falha:
        return falhar(f"Extrato baixado, mas o processamento falhou: {doc.falha}")
    status.atualizar(job_id, st.CONCLUIDO, "Extrato baixado e processado.", resultado)
    return {"status": "concluido", **resultado}
