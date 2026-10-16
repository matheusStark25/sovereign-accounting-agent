"""Motor de cálculo trabalhista e tributário (fonte única de regras e tabelas).

Todas as contas usam ``Decimal``. Nenhuma função devolve zero para esconder um
erro: dados faltando ou competência sem tabela levantam ``CalculoError``.
"""

from .decimo_terceiro import ResultadoDecimoTerceiro, calcular_decimo_terceiro
from .errors import CalculoError, CompetenciaSemTabela, DadosInvalidos, TipoNaoSuportado
from .ferias import ResultadoFerias, calcular_ferias
from .fgts import ResultadoFgts, calcular_fgts_mensal, calcular_multa_fgts
from .folha import ResultadoFolha, calcular_folha
from .inss import ResultadoInss, calcular_inss
from .irrf import ResultadoIrrf, calcular_irrf_mensal
from .rescisao import DadosRescisao, ResultadoRescisao, calcular_rescisao, dados_de_dict

__all__ = [
    "CalculoError",
    "CompetenciaSemTabela",
    "DadosInvalidos",
    "TipoNaoSuportado",
    "DadosRescisao",
    "ResultadoDecimoTerceiro",
    "ResultadoFerias",
    "ResultadoFgts",
    "ResultadoFolha",
    "ResultadoInss",
    "ResultadoIrrf",
    "ResultadoRescisao",
    "calcular_decimo_terceiro",
    "calcular_ferias",
    "calcular_fgts_mensal",
    "calcular_folha",
    "calcular_multa_fgts",
    "calcular_inss",
    "calcular_irrf_mensal",
    "calcular_rescisao",
    "dados_de_dict",
]
