"""DocumentDispatcher: orquestra o pipeline de documentos pelos 7 estados.

    RECEIVED -> CLASSIFYING -> PROCESSING -> REVIEWING -> CORRECTING -> DISPATCHING -> ARCHIVED

* Cada transição vira uma entrada da trilha WORM (HMAC encadeado); ``audit_trail_id`` aponta para a última.
* Worker (DeepSeek), Revisor (Gemini) e Corretor trabalham em modo determinístico se não houver chave de API.
* O pipeline nunca aceita do LLM um valor que não esteja no documento.
* Se uma etapa falha, a máquina fica no estado em que parou; só ``ARCHIVED`` quer dizer concluído.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from contabil_agente.documentos.leitura import ArquivoInvalido, Conteudo, ler_documento
from contabil_agente.documentos.processador import ResultadoDocumento, classificar, processar_conteudo, resolver_tipo_informado
from contabil_agente.documentos.tipos import TIPOS, Alerta, corpus
from contabil_agente.security.worm_audit import AuditoriaError, WormAudit

from .agentes import AgenteCorretor, AgenteRevisor, AgenteWorker, Divergencia
from .anomalias import DetectorDeAnomalias, HistoricoDocumentos
from .destinos import ArquivoDestino, Destino, ErroDeDestino
from .fsm import Estado, MaquinaDeEstados, Passo
from .provedores import provedores_do_ambiente

logger = logging.getLogger(__name__)
MAX_RODADAS_PADRAO = 2


class DocumentDispatcher:
    def __init__(
        self,
        audit: WormAudit,
        historico: Optional[HistoricoDocumentos] = None,
        worker_llm: Any = None,
        revisor_llm: Any = None,
        destinos: Optional[Sequence[Destino]] = None,
        max_rodadas: int = MAX_RODADAS_PADRAO,
        persona: str = "MARCOS",
        hoje: Optional[date] = None,
    ):
        self.audit = audit
        self.historico = historico
        self.detector = DetectorDeAnomalias(historico) if historico else None
        self.worker_llm, self.revisor_llm = worker_llm, revisor_llm
        self.corretor = AgenteCorretor()
        self.destinos: List[Destino] = list(destinos or [])
        self.max_rodadas, self.persona, self._hoje = max_rodadas, persona, hoje

    @classmethod
    def do_ambiente(cls, diretorio_de_dados: Union[str, Path], env: Optional[Mapping[str, str]] = None, **kw: Any) -> "DocumentDispatcher":
        """Auditoria, histórico, arquivo e provedores de LLM a partir do ambiente e de um diretório de dados."""
        base = Path(diretorio_de_dados)
        prov = provedores_do_ambiente(env)
        return cls(
            audit=WormAudit.do_ambiente(base / "audit", env),
            historico=HistoricoDocumentos(base / "documentos.db"),
            worker_llm=prov["worker"], revisor_llm=prov["revisor"],
            destinos=[ArquivoDestino(base / "arquivo")],
            **kw,
        )

    # --------------------------------------------------------------------- API
    def process(
        self,
        document_path: Union[str, Path, bytes, None] = None,
        document_type: Optional[str] = None,
        persona: Optional[str] = None,
        *,
        conteudo: Optional[bytes] = None,
        nome: Optional[str] = None,
        tenant: str = "default",
        ator: str = "sistema",
    ) -> ResultadoDocumento:
        """Processa um documento (caminho ou bytes) e devolve o resultado com ``extracted_data``,
        ``calculations`` e ``audit_trail_id``. Levanta ``ArquivoInvalido`` se o arquivo não puder ser lido."""
        origem = conteudo if conteudo is not None else document_path
        if origem is None:
            raise ArquivoInvalido("Informe document_path ou conteudo.")
        etapas: List[Dict[str, Any]] = []
        contexto = {"sha256": None, "tipo": None}

        def auditar(evento: str, extra: Optional[Dict[str, Any]] = None) -> str:
            dados = {"sha256": contexto["sha256"], "tipo": contexto["tipo"], **(extra or {})}
            return self.audit.append(f"documento.{evento}", dados, tenant=tenant, ator=ator).id

        def ao_transitar(p: Passo) -> None:
            etapas.append({"estado": p.para.value, "motivo": p.motivo, "em": p.em})
            auditar(p.para.value.lower(), {"motivo": p.motivo})

        # RECEIVED -------------------------------------------------------------
        try:
            conteudo_lido = ler_documento(origem, nome)
        except ArquivoInvalido as exc:
            self.audit.append("documento.falha", {"estado": "RECEIVED", "motivo": str(exc)}, tenant=tenant, ator=ator)
            raise
        contexto["sha256"] = conteudo_lido.sha256
        maquina = MaquinaDeEstados(ao_transitar=ao_transitar)
        etapas.append({"estado": "RECEIVED", "motivo": "documento recebido", "em": maquina.historico[0].em})
        auditar("received", {"formato": conteudo_lido.formato, "paginas": conteudo_lido.paginas})

        def falhar(motivo: str, resultado: Optional[ResultadoDocumento] = None) -> ResultadoDocumento:
            maquina.falhar(motivo)
            recibo = self.audit.append("documento.falha", {"estado": maquina.estado.value, "motivo": motivo, "sha256": contexto["sha256"], "tipo": contexto["tipo"]}, tenant=tenant, ator=ator).id
            base = resultado or ResultadoDocumento(None, None, 0.0, [], {}, {}, [], list(conteudo_lido.avisos), [], conteudo_lido.formato, conteudo_lido.sha256, conteudo_lido.paginas)
            base.estado, base.falha, base.audit_trail_id, base.etapas = maquina.estado.value, motivo, recibo, etapas
            base.requer_revisao = True
            return base

        # CLASSIFYING ----------------------------------------------------------
        maquina.transitar(Estado.CLASSIFYING, "identificando o tipo do documento")
        tipo_codigo, motivo_tipo = self._classificar(conteudo_lido, document_type, persona)
        if tipo_codigo is None:
            return falhar(motivo_tipo)
        contexto["tipo"] = tipo_codigo

        # PROCESSING -----------------------------------------------------------
        maquina.transitar(Estado.PROCESSING, f"extração e conferência de {tipo_codigo}")
        resultado = processar_conteudo(conteudo_lido, tipo_codigo)
        texto = corpus(conteudo_lido)
        worker = AgenteWorker(self.worker_llm, persona or self.persona).processar(texto, tipo_codigo, resultado.extracted_data, resultado.resumo)
        resultado.agentes = {"worker": worker.origem}
        if worker.erro:
            resultado.avisos.append(f"Worker em modo determinístico: {worker.erro}")
        resultado.resumo = worker.resumo

        # REVIEWING <-> CORRECTING --------------------------------------------
        revisor = AgenteRevisor(self.revisor_llm)
        sugestoes = dict(worker.sugestoes)
        pendentes: List[Divergencia] = []
        rodada = 0
        while True:
            rodada += 1
            maquina.transitar(Estado.REVIEWING, f"revisão (rodada {rodada})")
            revisao = revisor.revisar(texto, tipo_codigo, resultado.extracted_data, resultado.alertas, conteudo_lido.formato)
            resultado.agentes["revisor"] = revisao.origem
            if revisao.erro:
                resultado.avisos.append(f"Revisor em modo determinístico: {revisao.erro}")
            pendentes = revisao.divergencias
            if (not pendentes and not sugestoes) or rodada > self.max_rodadas:
                break
            maquina.transitar(Estado.CORRECTING, f"{len(pendentes)} divergência(s) e {len(sugestoes)} sugestão(ões) a tratar")
            correcao = self.corretor.corrigir(texto, resultado.extracted_data, pendentes, sugestoes)
            resultado.extracted_data = correcao.dados
            resultado.correcoes += [c.to_dict() for c in correcao.aplicadas]
            resultado.rejeitadas += correcao.rejeitadas
            sugestoes = {}
            self._reconferir(resultado, conteudo_lido, tipo_codigo)
            if not correcao.aplicadas:
                break  # nada mais a fazer: CORRECTING -> DISPATCHING com as pendências registradas
        resultado.divergencias = [d.to_dict() for d in pendentes]
        if pendentes:
            resultado.alertas.append(Alerta("divergencias_nao_resolvidas", f"{len(pendentes)} divergência(s) sem correção possível: revisão humana necessária.", "aviso"))
        resultado.agentes.setdefault("corretor", "regras")

        # anomalias (antes de despachar) --------------------------------------
        if self.detector is not None:
            resultado.alertas += self.detector.avaliar(tenant, tipo_codigo, resultado.extracted_data, conteudo_lido.sha256, self._hoje)
        resultado.requer_revisao = any(a.severidade in ("erro",) or a.codigo in ("documento_duplicado", "divergencias_nao_resolvidas", "valor_atipico") for a in resultado.alertas)

        # DISPATCHING ----------------------------------------------------------
        maquina.transitar(Estado.DISPATCHING, "arquivando e enviando aos destinos")
        resultado.resumo = self._resumo_final(resultado)
        resultado.estado, resultado.etapas = maquina.estado.value, etapas
        corpo = resultado.to_dict()
        nome_arquivo = nome or (str(origem) if isinstance(origem, (str, Path)) else "")
        extensao = Path(nome_arquivo).suffix.lower()
        envio = {"tenant": tenant, "tipo": tipo_codigo, "sha256": conteudo_lido.sha256, "resultado": corpo,
                 "bytes": conteudo_lido.bruto, "extensao": extensao if re.fullmatch(r"\.[a-z0-9]{1,8}", extensao) else None}
        for i, destino in enumerate(self.destinos):
            try:
                resultado.destinos.append({"destino": destino.nome, **destino.enviar(envio)})
            except (ErroDeDestino, OSError) as exc:
                if i == 0 and isinstance(destino, ArquivoDestino):
                    return falhar(f"Não consegui arquivar: {exc}", resultado)
                resultado.alertas.append(Alerta("destino_falhou", f"Destino {destino.nome} falhou: {exc}", "aviso"))

        # ARCHIVED -------------------------------------------------------------
        maquina.transitar(Estado.ARCHIVED, "concluído")
        resultado.estado = maquina.estado.value
        resultado.etapas = etapas
        try:
            resultado.audit_trail_id = auditar(
                "arquivado",
                {"alertas": len(resultado.alertas), "correcoes": len(resultado.correcoes), "requer_revisao": resultado.requer_revisao,
                 "agentes": resultado.agentes, "caminho": [p.para.value for p in maquina.historico]},
            )
        except AuditoriaError as exc:
            return falhar(f"Trilha de auditoria indisponível: {exc}", resultado)
        if self.historico is not None:
            self.historico.registrar(tenant, conteudo_lido.sha256, tipo_codigo, resultado.extracted_data, resultado.audit_trail_id)
        return resultado

    # ----------------------------------------------------------------- interno
    def _classificar(self, c: Conteudo, tipo_informado: Optional[str], persona: Optional[str]):
        if tipo_informado:
            try:
                codigo = resolver_tipo_informado(tipo_informado)
            except ValueError as exc:
                return None, str(exc)
            if codigo is not None:
                return codigo, ""
            restrito = [k for k, t in TIPOS.items() if t.categoria == "sped"]
            codigo, _, _ = classificar(c, restrito)
            return (codigo, "") if codigo else (None, "Não consegui identificar qual tipo de SPED é o arquivo.")
        codigo, _, _ = classificar(c)
        if codigo:
            return codigo, ""
        if self.worker_llm is not None:  # a IA pode sugerir, mas só vale se houver ao menos um indício no texto
            try:
                resposta = self.worker_llm.gerar_json(
                    "Classifique o documento. Responda SOMENTE um JSON {\"tipo\": \"CODIGO\"} com um destes códigos: " + ", ".join(sorted(TIPOS)),
                    c.texto,
                )
                sugerido = str(resposta.get("tipo", "")).upper()
                from contabil_agente.documentos.processador import pontuar

                if sugerido in TIPOS and dict(pontuar(c)).get(sugerido, 0) >= 1:
                    return sugerido, ""
            except Exception:  # noqa: BLE001 - qualquer falha do provedor cai no erro padrão abaixo
                logger.info("Classificação por LLM indisponível.")
        return None, "Não consegui identificar o tipo do documento (informe document_type)."

    @staticmethod
    def _reconferir(resultado: ResultadoDocumento, c: Conteudo, codigo: str) -> None:
        tipo = TIPOS[codigo]
        resultado.faltando = [k for k in tipo.esperados if k not in resultado.extracted_data]
        if tipo.conferir is not None:
            alertas, calculos = tipo.conferir(resultado.extracted_data, c)
            antigos = [a for a in resultado.alertas if a.codigo in ("tipo_nao_confirmado", "tipo_informado_diverge")]
            resultado.alertas, resultado.calculations = antigos + alertas, calculos

    @staticmethod
    def _resumo_final(r: ResultadoDocumento) -> str:
        partes = [r.resumo.rstrip(".")]
        if r.correcoes:
            partes.append(f"{len(r.correcoes)} correção(ões) aplicada(s)")
        if r.requer_revisao:
            partes.append("requer revisão humana")
        return "; ".join(partes) + "."
