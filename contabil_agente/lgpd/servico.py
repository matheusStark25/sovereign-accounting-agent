"""Serviço de LGPD: base legal, consentimento, retenção e direito de exclusão, sempre com trilha WORM.

* ``exigir_base_legal`` recusa tratamento sem finalidade cadastrada ou, quando a base é consentimento,
  sem consentimento ativo.
* ``executar_retencao`` expurga o que passou do prazo (conversas, documentos arquivados, histórico, temporários).
* ``excluir_titular`` (art. 18, VI) apaga dados do titular identificado por CPF/CNPJ, **exceto** o que está
  dentro de prazo legal de guarda (art. 16, I): isso fica retido e é listado no relatório com a data em que
  poderá ser apagado.
* A trilha de auditoria guarda só dados mascarados e o hash do titular, nunca o CPF.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from contabil_agente.chat.store import ChatStore
from contabil_agente.pipeline.anomalias import HistoricoDocumentos
from contabil_agente.security.worm_audit import WormAudit

from .anonimizacao import PIIAnonymizer
from .base_legal import TratamentoSemBaseLegal, exige_consentimento, finalidade
from .consentimento import TITULAR_SISTEMA, ConsentimentoStore
from .retencao import PoliticaDeRetencao, idade_em_dias


def _variantes_do_documento(doc: str) -> List[str]:
    d = re.sub(r"\D", "", doc)
    saida = {d}
    if len(d) == 11:
        saida.add(f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}")
    if len(d) == 14:
        saida.add(f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}")
    return sorted(saida, key=len, reverse=True)


class ServicoLGPD:
    def __init__(
        self,
        audit: WormAudit,
        consentimentos: ConsentimentoStore,
        politica: Optional[PoliticaDeRetencao] = None,
        raiz_arquivo: Optional[str | Path] = None,
        chat_store: Optional[ChatStore] = None,
        historico: Optional[HistoricoDocumentos] = None,
        chave_hash: Optional[str] = None,
    ):
        self.audit, self.consentimentos = audit, consentimentos
        self.politica = politica or PoliticaDeRetencao()
        self.raiz_arquivo = Path(raiz_arquivo) if raiz_arquivo else None
        self.chat_store, self.historico = chat_store, historico
        self._chave_hash = chave_hash or consentimentos._chave

    # ------------------------------------------------------------- base legal
    def exigir_base_legal(self, codigo_finalidade: str, tenant: str, titular: Optional[str] = None) -> str:
        """Devolve a base legal ou levanta ``TratamentoSemBaseLegal``."""
        f = finalidade(codigo_finalidade)
        if exige_consentimento(codigo_finalidade):
            if not (self.consentimentos.ativo(tenant, titular, codigo_finalidade) or self.consentimentos.ativo(tenant, TITULAR_SISTEMA, codigo_finalidade)):
                raise TratamentoSemBaseLegal(f"A finalidade {codigo_finalidade!r} exige consentimento ativo ({f.base.value}).")
        return f.base.value

    def pode_tratar(self, codigo_finalidade: str, tenant: str, titular: Optional[str] = None) -> bool:
        try:
            self.exigir_base_legal(codigo_finalidade, tenant, titular)
            return True
        except TratamentoSemBaseLegal:
            return False

    # ------------------------------------------------------------ consentimento
    def registrar_consentimento(self, tenant: str, titular: Optional[str], codigo_finalidade: str, concedido: bool, ator: str) -> int:
        n = self.consentimentos.registrar(tenant, titular, codigo_finalidade, concedido, ator)
        self.audit.append(
            "lgpd.consentimento", {"finalidade": codigo_finalidade, "concedido": concedido, "titular": self._hash(titular)}, tenant=tenant, ator=ator
        )
        return n

    def _hash(self, titular: Optional[str]) -> str:
        return TITULAR_SISTEMA if titular in (None, "", TITULAR_SISTEMA) else PIIAnonymizer.hash_pii(titular, self._chave_hash)

    # ----------------------------------------------------------------- retenção
    def executar_retencao(self, tenant: str, ator: str = "sistema", agora: Optional[float] = None) -> Dict[str, int]:
        agora = agora if agora is not None else time.time()
        relatorio = {"chat": 0, "documentos": 0, "historico": 0, "temporarios": 0}
        if self.chat_store is not None and self.politica.prazo("chat") is not None:
            relatorio["chat"] = self.chat_store.purgar_expiradas(self.politica.prazo("chat"))
        if self.raiz_arquivo is not None:
            pasta = self.raiz_arquivo / tenant
            if pasta.is_dir():
                for arquivo in list(pasta.rglob("*")):
                    if arquivo.is_file() and self.politica.vencido("documentos", idade_em_dias(arquivo.stat().st_mtime, agora)):
                        arquivo.unlink()
                        relatorio["documentos"] += 1
        self.audit.append("lgpd.retencao", {"removidos": relatorio, "politica": self.politica.para_dict()}, tenant=tenant, ator=ator)
        return relatorio

    # ------------------------------------------------------------------ exclusão
    def excluir_titular(self, tenant: str, documento_do_titular: str, ator: str, agora: Optional[float] = None) -> Dict[str, Any]:
        """Apaga dados do titular (CPF/CNPJ) no tenant, respeitando prazo legal de guarda.

        Devolve ``{"apagados": [...], "retidos": [{"arquivo", "motivo", "apagavel_em"}], "conversas_editadas": n, "consentimentos": n}``.
        """
        agora = agora if agora is not None else time.time()
        variantes = _variantes_do_documento(documento_do_titular)
        if not variantes[0] or len(variantes[0]) not in (11, 14):
            raise ValueError("Informe um CPF (11 dígitos) ou CNPJ (14 dígitos).")
        digitos = variantes[0]
        apagados: List[str] = []
        retidos: List[Dict[str, Any]] = []
        prazo = self.politica.prazo("documentos")
        if self.raiz_arquivo is not None and (self.raiz_arquivo / tenant).is_dir():
            for arquivo in sorted((self.raiz_arquivo / tenant).rglob("*")):
                if not arquivo.is_file() or not self._contem(arquivo, variantes, digitos):
                    continue
                idade = idade_em_dias(arquivo.stat().st_mtime, agora)
                if prazo is not None and idade < prazo:
                    retidos.append({
                        "arquivo": str(arquivo.relative_to(self.raiz_arquivo)),
                        "motivo": "dentro do prazo legal de guarda (LGPD art. 16, I)",
                        "apagavel_em_dias": int(prazo - idade) + 1,
                    })
                else:
                    arquivo.unlink()
                    apagados.append(str(arquivo.relative_to(self.raiz_arquivo)))
        conversas = self._limpar_conversas(tenant, variantes)
        consentimentos = self.consentimentos.apagar_do_titular(tenant, documento_do_titular)
        self.audit.append(
            "lgpd.exclusao",
            {"titular": self._hash(documento_do_titular), "apagados": len(apagados), "retidos": len(retidos), "conversas_editadas": conversas, "consentimentos": consentimentos},
            tenant=tenant, ator=ator,
        )
        return {"apagados": apagados, "retidos": retidos, "conversas_editadas": conversas, "consentimentos": consentimentos}

    @staticmethod
    def _contem(arquivo: Path, variantes: List[str], digitos: str) -> bool:
        try:
            bruto = arquivo.read_bytes()
        except OSError:
            return False
        texto = bruto.decode("utf-8", errors="ignore")
        if any(v in texto for v in variantes):
            return True
        return digitos in re.sub(r"\D", "", texto)

    def _limpar_conversas(self, tenant: str, variantes: List[str]) -> int:
        """Troca o documento por ***CPF*** nas conversas do tenant (as conversas em si ficam)."""
        if self.chat_store is None:
            return 0
        editadas = 0
        with self.chat_store._db() as con:
            for linha in con.execute("SELECT id, user_id, estado FROM chat_sessions WHERE tenant_id = ?", (tenant,)).fetchall():
                estado = linha[2]
                novo = estado
                for v in variantes:
                    novo = novo.replace(v, "***DOCUMENTO***")
                if novo != estado:
                    con.execute("UPDATE chat_sessions SET estado = ? WHERE id = ?", (novo, linha[0]))
                    editadas += 1
        return editadas
