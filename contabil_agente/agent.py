"""AgenteContabil: calcula, gera o PDF e registra o hash de integridade.

Fluxo de ``processar_pedido``: calcular (motor ``contabil_agente.calc``) -> PDF com campos de
formulário -> SHA-256 do PDF e do resultado -> evento de auditoria. Nada é estimado: se faltar dado
ou a legislação carregada não cobrir a data, o retorno explica o motivo e nenhum PDF é gerado.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import date
from typing import Any, Callable, Dict, Optional

from contabil_agente.calc.servico import TIPOS_CALCULO, calcular
from contabil_agente.documentos import gerar_pdf_calculo, hash_do_resultado

logger = logging.getLogger("contabil_agente.agent")

Auditoria = Callable[[str, Dict[str, Any]], None]


def inferir_tipo(dados: Dict[str, Any]) -> str:
    """``tipo_calculo`` explícito; senão rescisão (se houver demissão) ou folha (salário simples)."""
    tipo = str(dados.get("tipo_calculo") or "").strip().lower()
    if tipo:
        return tipo
    if dados.get("data_demissao") or dados.get("tipo_rescisao"):
        return "rescisao"
    return "folha"


class AgenteContabil:
    def __init__(self, auditoria: Optional[Auditoria] = None, hoje: Optional[date] = None):
        self._auditoria = auditoria
        self._hoje = hoje

    def _auditar(self, evento: str, detalhes: Dict[str, Any]) -> None:
        if self._auditoria is None:
            return
        try:
            self._auditoria(evento, detalhes)
        except Exception:
            logger.exception("Falha ao registrar auditoria (%s)", evento)

    def calcular(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Resposta de ``calc.servico.calcular`` (status ok, faltam_dados ou erro)."""
        dados = dict(dados or {})
        if "salario_bruto" in dados and "salario" not in dados and "salario_base" not in dados:
            dados["salario"] = dados["salario_bruto"]
        tipo = inferir_tipo(dados)
        resposta = calcular(tipo, dados, self._hoje)
        self._auditar("calculo", {"tipo": tipo, "status": resposta["status"]})
        return resposta

    def gerar_pdf(self, tipo: str, resultado: Dict[str, Any], contexto: Optional[Dict[str, Any]] = None) -> bytes:
        pdf = gerar_pdf_calculo(tipo, resultado, contexto)
        self._auditar("pdf", {"tipo": tipo, "bytes": len(pdf)})
        return pdf

    @staticmethod
    def assinar(pdf: bytes, resultado: Dict[str, Any]) -> Dict[str, Any]:
        """Hashes de integridade (SHA-256 do PDF e do resultado). A assinatura digital fica em ``security``."""
        return {
            "metodo": "sha256",
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            "resultado_sha256": hash_do_resultado(resultado),
        }

    def processar_pedido(
        self, dados: Dict[str, Any], contexto: Optional[Dict[str, Any]] = None, incluir_pdf: bool = False
    ) -> Dict[str, Any]:
        resposta = self.calcular(dados)
        if resposta["status"] != "ok":
            return {"success": False, **resposta}
        tipo, resultado = resposta["tipo"], resposta["resultado"]
        if tipo not in TIPOS_CALCULO:
            return {"success": False, "status": "erro", "mensagem": f"Tipo sem processamento: {tipo}"}
        pdf = self.gerar_pdf(tipo, resultado, contexto)
        saida = {
            "success": True,
            "tipo": tipo,
            "resultado": resultado,
            "resumo": resposta["resumo"],
            "pendencias": resposta["pendencias"],
            "assinatura": self.assinar(pdf, resultado),
            "pdf_bytes": len(pdf),
        }
        if incluir_pdf:
            saida["pdf_base64"] = base64.b64encode(pdf).decode("ascii")
        self._auditar("pedido_processado", {"tipo": tipo, "sha256": saida["assinatura"]["pdf_sha256"]})
        return saida
