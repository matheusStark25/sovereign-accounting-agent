"""RPAAgent: pede o extrato do FGTS (CPF), do PGMEI (CNPJ) ou o resumo de uma NF-e (chave) ao robô e acompanha o trabalho.

O robô abre um navegador de verdade e **uma pessoa resolve só o captcha ou o login**; o PDF baixado entra no pipeline de
documentos. Se o portal recusar navegador automatizado, o trabalho termina dizendo o que fazer (baixar o PDF e enviá-lo ao
sistema). Quem enfileira e quem consulta o estado vêm de fora (a API do sistema), então o agente não conhece fila nem banco.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .base import Agente, AgenteErro, exigir_campo

PORTAIS = {
    "fgts": "Extrato do FGTS do trabalhador (portal da Caixa), por CPF",
    "pgmei": "Extrato/DAS do MEI (portal da Receita Federal), por CNPJ",
    "nfe": "Resumo de uma NF-e, CT-e ou NFC-e (portais da SEFAZ), pela chave de acesso de 44 dígitos",
}


class RPAAgent(Agente):
    nome = "RPAAgent"
    descricao = (
        "Pede o extrato do FGTS (CPF), do PGMEI (CNPJ) ou o resumo de uma NF-e (chave) a um navegador em que a pessoa resolve só o captcha/login, e "
        "acompanha o trabalho até o PDF entrar no pipeline de documentos (ou o resumo da nota ficar pronto)."
    )

    def __init__(self, enfileirar: Callable[[str, str, Optional[int]], Dict[str, Any]], estado: Callable[[str], Optional[Dict[str, Any]]]):
        self._enfileirar, self._estado = enfileirar, estado

    def acao_portais(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Lista os portais que o robô atende."""
        return {"portais": [{"portal": p, "descricao": d} for p, d in PORTAIS.items()]}

    def acao_solicitar_extrato(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Enfileira o extrato: ``{"portal": "fgts"|"pgmei"|"nfe", "documento": CPF/CNPJ/chave, "ano": opcional (pgmei)}``."""
        portal = str(exigir_campo(dados, "portal", str)).strip().lower()
        if portal not in PORTAIS:
            raise AgenteErro(f"Portal desconhecido: {portal!r}. Use: {', '.join(PORTAIS)}.")
        documento = exigir_campo(dados, "documento", str)
        ano = dados.get("ano")
        if ano is not None and (not isinstance(ano, int) or isinstance(ano, bool) or not 2000 <= ano <= 2100):
            raise AgenteErro("O campo 'ano' precisa ser um número entre 2000 e 2100.")
        return dict(self._enfileirar(portal, documento, ano))

    def acao_estado(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Estado de um trabalho do robô: ``{"job_id": "..."}``."""
        job = self._estado(str(exigir_campo(dados, "job_id", str)))
        if job is None:
            raise AgenteErro("Trabalho não encontrado.")
        return {"trabalho": job}
