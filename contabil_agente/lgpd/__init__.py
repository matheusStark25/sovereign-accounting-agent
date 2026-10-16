"""LGPD: anonimização, base legal (art. 7), consentimento por titular, retenção e direito de exclusão.

``ServicoLGPD`` é importado sob demanda para que módulos de baixo nível (trilha de auditoria, chat)
possam usar ``PIIAnonymizer`` sem criar importação circular.
"""

from .anonimizacao import PIIAnonymizer
from .base_legal import FINALIDADES, BaseLegal, Finalidade, TratamentoSemBaseLegal, finalidade
from .consentimento import TITULAR_SISTEMA, ConsentimentoStore
from .retencao import PADRAO, PoliticaDeRetencao, PoliticaInvalida

__all__ = [
    "PIIAnonymizer", "FINALIDADES", "BaseLegal", "Finalidade", "TratamentoSemBaseLegal", "finalidade",
    "TITULAR_SISTEMA", "ConsentimentoStore", "PADRAO", "PoliticaDeRetencao", "PoliticaInvalida", "ServicoLGPD",
]


def __getattr__(nome):
    if nome == "ServicoLGPD":
        from .servico import ServicoLGPD

        return ServicoLGPD
    raise AttributeError(nome)
