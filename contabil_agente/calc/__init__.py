"""Motor de cálculo trabalhista e tributário (fonte única de regras e tabelas).

Todas as contas usam ``Decimal``. Nenhuma função devolve zero para esconder um
erro: dados faltando ou competência sem tabela levantam ``CalculoError``.
"""

from .errors import CalculoError, CompetenciaSemTabela, DadosInvalidos, TipoNaoSuportado
from .inss import ResultadoInss, calcular_inss
from .irrf import ResultadoIrrf, calcular_irrf_mensal

__all__ = [
    "CalculoError",
    "CompetenciaSemTabela",
    "DadosInvalidos",
    "TipoNaoSuportado",
    "ResultadoInss",
    "ResultadoIrrf",
    "calcular_inss",
    "calcular_irrf_mensal",
]
