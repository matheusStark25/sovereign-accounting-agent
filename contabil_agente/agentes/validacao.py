"""ValidationAgent: confere identificadores e documentos (dígitos verificadores, estrutura, conferências cruzadas)."""

from __future__ import annotations

import base64
import binascii
from typing import Any, Dict

from contabil_agente.documentos.leitura import ArquivoInvalido
from contabil_agente.documentos.processador import TipoDesconhecido, processar_documento
from contabil_agente.documentos.validadores import mascarar_cnpj, mascarar_cpf, validar_chave_acesso, validar_cnpj, validar_cpf, validar_pis

from .base import Agente, AgenteErro, exigir_campo

_VALIDADORES = {"cpf": validar_cpf, "cnpj": validar_cnpj, "pis": validar_pis, "chave_nfe": validar_chave_acesso}
_MAX_IDENTIFICADORES = 500


def _mascara(tipo: str, valor: Any) -> str:
    if tipo == "cpf":
        return mascarar_cpf(valor)
    if tipo == "cnpj":
        return mascarar_cnpj(valor)
    texto = "".join(c for c in str(valor) if c.isdigit())
    return f"{texto[:3]}***{texto[-2:]}" if len(texto) > 5 else "***"


class ValidationAgent(Agente):
    nome = "ValidationAgent"
    descricao = (
        "Valida CPF, CNPJ, PIS e chave de acesso de NF-e pelo dígito verificador e processa um documento (PDF, XML, TXT, CSV): "
        "classifica, extrai e confere. O que volta não repete o identificador por inteiro (só mascarado)."
    )

    def acao_identificadores(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Valida uma lista ``[{"tipo": "cpf", "valor": "..."}]`` (cpf, cnpj, pis, chave_nfe)."""
        itens = exigir_campo(dados, "itens", list)
        if len(itens) > _MAX_IDENTIFICADORES:
            raise AgenteErro(f"No máximo {_MAX_IDENTIFICADORES} identificadores por pedido.")
        saida = []
        for n, item in enumerate(itens, 1):
            if not isinstance(item, dict) or "valor" not in item:
                raise AgenteErro(f"Item {n}: use {{\"tipo\": ..., \"valor\": ...}}.")
            tipo = str(item.get("tipo", "")).strip().lower()
            validador = _VALIDADORES.get(tipo)
            if validador is None:
                raise AgenteErro(f"Item {n}: tipo {tipo!r} desconhecido. Use: {', '.join(_VALIDADORES)}.")
            saida.append({"tipo": tipo, "valido": bool(validador(item["valor"])), "mascarado": _mascara(tipo, item["valor"])})
        return {"itens": saida, "todos_validos": all(i["valido"] for i in saida)}

    def acao_documento(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Classifica, extrai e confere um documento: ``{"conteudo_base64": ..., "nome": "x.pdf", "tipo": opcional}``."""
        bruto = exigir_campo(dados, "conteudo_base64", str)
        try:
            conteudo = base64.b64decode(bruto, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AgenteErro("conteudo_base64 não é Base64 válido.") from exc
        try:
            r = processar_documento(conteudo, dados.get("tipo"), dados.get("nome"))
        except (ArquivoInvalido, TipoDesconhecido) as exc:
            raise AgenteErro(str(exc)) from exc
        return {
            "tipo": r.tipo, "confianca": r.confianca, "formato": r.formato, "sha256": r.sha256, "faltando": r.faltando,
            "extraido": r.extracted_data, "calculos": r.calculations,
            "alertas": [a.to_dict() for a in r.alertas], "resumo": r.resumo,
        }
