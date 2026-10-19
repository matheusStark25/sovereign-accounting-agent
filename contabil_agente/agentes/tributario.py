"""TaxAgent: cálculos trabalhistas, previdenciários e tributários pelo motor ``calc`` (Decimal, tabelas oficiais por competência)."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from contabil_agente.calc import servico

from .base import Agente, exigir_campo


class TaxAgent(Agente):
    nome = "TaxAgent"
    descricao = (
        "Calcula rescisão, férias, 13º, INSS, IRRF, FGTS, folha, pró-labore, GPS, DAS do MEI e DARF em atraso com o motor "
        "de cálculo (nunca por modelo de linguagem). Falta de dado vira pergunta; competência sem tabela vira erro."
    )

    def __init__(self, hoje: Optional[date] = None):
        self.hoje = hoje

    def acao_tipos(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Lista os cálculos que o motor faz."""
        return {"tipos": list(servico.TIPOS_CALCULO)}

    def acao_calcular(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Executa um cálculo: ``{"tipo": "rescisao", "dados": {...}}``."""
        tipo = exigir_campo(dados, "tipo", str)
        entrada = exigir_campo(dados, "dados", dict)
        resposta = servico.calcular(tipo, entrada, hoje=self.hoje)
        return {key: resposta[key] for key in resposta if key != "status"} | {"status": resposta["status"]}
