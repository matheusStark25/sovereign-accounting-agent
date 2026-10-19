"""Tarefas do robô: decifra o CPF/CNPJ/chave, roda o robô (com pausa para a pessoa) e processa o PDF no pipeline (a consulta de NF-e devolve o resumo)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from contabil_agente.lgpd import TratamentoSemBaseLegal
from contabil_agente.lgpd.anonimizacao import PIIAnonymizer
from contabil_agente.resilience import CircuitoAberto
from contabil_agente.rpa import (
    MODELOS, ErroDoRobo, HumanoNaoRespondeu, PortalBloqueouAutomacao, RoboConsultaNFe, RoboExtratoFGTS, RoboExtratoPGMEI, config_para_chave,
    modelo_da_chave,
)
from contabil_agente.rpa import estado as st
from contabil_agente.security import pqc

from . import celery_app
from .contexto import obter_contexto

logger = logging.getLogger(__name__)


def _aad(tenant: str, job_id: str, portal: str = "fgts") -> bytes:
    return f"rpa-{portal}|{tenant}|{job_id}".encode("utf-8")


def envelope_do_cpf(chave_publica: Dict[str, str], cpf: str, tenant: str, job_id: str, portal: str = "fgts") -> Dict[str, str]:
    """Cifra o CPF (ou CNPJ) para o worker (ML-KEM-768 + X25519 + AES-GCM) antes de ir para o broker."""
    return pqc.cifrar_hibrido(chave_publica, cpf.encode("utf-8"), _aad(tenant, job_id, portal))


def abrir_cpf(chave_privada: Dict[str, str], envelope: Dict[str, str], tenant: str, job_id: str, portal: str = "fgts") -> str:
    return pqc.decifrar_hibrido(chave_privada, envelope, _aad(tenant, job_id, portal)).decode("utf-8")


def _executar_extrato(job_id: str, tenant: str, ator: str, envelope: Dict[str, str], *, portal: str, nome: str, finalidade: str,
                      tipo_documento: str, ano: Optional[int] = None) -> Dict[str, Any]:
    """Decifra o documento, roda o robô do portal (com a pessoa resolvendo o captcha/login) e processa o PDF no pipeline."""
    ctx = obter_contexto()
    status = ctx.status

    def falhar(mensagem: str) -> Dict[str, Any]:
        status.atualizar(job_id, st.FALHOU, mensagem)
        ctx.audit.append(f"rpa.{portal}.job_falhou", {"job": job_id, "motivo": mensagem}, tenant=tenant, ator=ator)
        return {"status": "falhou", "mensagem": mensagem}

    if ctx.chave_privada_rpa is None:
        return falhar("Chave privada do RPA (RPA_PQC_PRIVATE_KEY) não configurada neste worker.")
    try:
        documento = abrir_cpf(ctx.chave_privada_rpa, envelope, tenant, job_id, portal)
    except pqc.PQCError:
        return falhar("Não consegui decifrar o documento: envelope adulterado ou chave errada.")
    try:
        ctx.lgpd.exigir_base_legal(finalidade, tenant, documento)  # revalida no worker: o consentimento pode ter sido revogado
    except TratamentoSemBaseLegal as exc:
        return falhar(str(exc))

    status.atualizar(job_id, st.EXECUTANDO, f"Abrindo o portal {nome}.")

    def notificar(motivo: str, seletor: str, page: Any) -> None:
        status.atualizar(job_id, st.AGUARDANDO_HUMANO, f"Resolva na janela do navegador: {motivo}.")
        if ctx.ao_pausar is not None:
            ctx.ao_pausar(motivo, seletor, page)

    if portal == "nfe":  # NF-e, CT-e ou NFC-e: o modelo gravado na chave escolhe o portal
        try:
            config_doc = config_para_chave(documento, ctx.config_nfe, ctx.config_cte, ctx.config_nfce)
        except ErroDoRobo as exc:
            return falhar(f"Robô: {exc}")
        robo = RoboConsultaNFe(config_doc, ctx.pasta_de_trabalho / job_id, ctx.audit, tenant=tenant, ator=ator, notificar_humano=notificar, chave_hash=ctx.chave_hash)
    elif portal == "pgmei":
        robo = RoboExtratoPGMEI(ctx.config_pgmei, ctx.pasta_de_trabalho / job_id, ctx.audit, tenant=tenant, ator=ator, notificar_humano=notificar, chave_hash=ctx.chave_hash)
    else:
        robo = RoboExtratoFGTS(ctx.config_fgts, ctx.pasta_de_trabalho / job_id, ctx.audit, tenant=tenant, ator=ator, notificar_humano=notificar, chave_hash=ctx.chave_hash)
    try:
        extrato = robo.executar(documento, ano=ano) if portal == "pgmei" else robo.executar(documento)
    except HumanoNaoRespondeu:
        return falhar("Ninguém resolveu o captcha/login a tempo.")
    except CircuitoAberto as exc:
        return falhar(f"Portal temporariamente suspenso após falhas seguidas: {exc}")
    except PortalBloqueouAutomacao:
        return falhar("O portal bloqueou o navegador automatizado. Baixe o extrato no seu navegador normal: com o observar-pasta ligado ele entra "
                      "sozinho; sem ele, envie o PDF pelo sistema (POST /api/v1/documentos)."
                      if portal != "nfe" else "O portal bloqueou o navegador automatizado. Consulte a nota no seu navegador normal.")
    except ErroDoRobo as exc:
        return falhar(f"Robô: {exc.motivo}")

    if portal == "nfe":  # a consulta devolve o resumo da nota (JSON), não um PDF para o pipeline
        tipo = "CONSULTA_" + MODELOS.get(modelo_da_chave(documento), "DOC").replace("-", "").upper()
        resumo = {"sha256": extrato.sha256, "tipo": tipo, "modelo": extrato.dados.get("modelo"), "resumo": extrato.dados.get("resumo", {}),
                  "titular": PIIAnonymizer.hash_pii(documento, ctx.chave_hash)}
        ctx.audit.append("rpa.nfe.job_concluido", {"job": job_id, "sha256": extrato.sha256}, tenant=tenant, ator=ator)
        status.atualizar(job_id, st.CONCLUIDO, "Consulta concluída.", resumo)
        return {"status": "concluido", **resumo}
    usar_ia = ctx.lgpd.pode_tratar("envio_a_provedor_de_ia", tenant)
    doc = ctx.dispatcher.process(document_path=extrato.caminho, document_type=tipo_documento, tenant=tenant, ator=ator, usar_ia=usar_ia)
    resultado = {
        "sha256": extrato.sha256,
        "tipo": doc.tipo,
        "estado": doc.estado,
        "audit_trail_id": doc.audit_trail_id,
        "alertas": [a.codigo for a in doc.alertas],
        "requer_revisao": doc.requer_revisao,
        "titular": PIIAnonymizer.hash_pii(documento, ctx.chave_hash),
    }
    if doc.falha:
        return falhar(f"Extrato baixado, mas o processamento falhou: {doc.falha}")
    status.atualizar(job_id, st.CONCLUIDO, "Extrato baixado e processado.", resultado)
    return {"status": "concluido", **resultado}


@celery_app.task(name="rpa.extrato_fgts", bind=True, max_retries=0)
def extrato_fgts(self, job_id: str, tenant: str, ator: str, envelope: Dict[str, str]) -> Dict[str, Any]:
    return _executar_extrato(job_id, tenant, ator, envelope, portal="fgts", nome="do FGTS", finalidade="consulta_extrato_fgts", tipo_documento="FGTS_EXTRATO")


@celery_app.task(name="rpa.extrato_pgmei", bind=True, max_retries=0)
def extrato_pgmei(self, job_id: str, tenant: str, ator: str, envelope: Dict[str, str], ano: Optional[int] = None) -> Dict[str, Any]:
    return _executar_extrato(job_id, tenant, ator, envelope, portal="pgmei", nome="do PGMEI", finalidade="consulta_extrato_pgmei", tipo_documento="DAS", ano=ano)


@celery_app.task(name="rpa.consulta_nfe", bind=True, max_retries=0)
def consulta_nfe(self, job_id: str, tenant: str, ator: str, envelope: Dict[str, str]) -> Dict[str, Any]:
    return _executar_extrato(job_id, tenant, ator, envelope, portal="nfe", nome="da NF-e", finalidade="consulta_nfe", tipo_documento="NFE")
