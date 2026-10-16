"""Ponto de entrada da LGPD (implementação em ``contabil_agente.lgpd``)."""

from contabil_agente.lgpd import (  # noqa: F401
    BaseLegal,
    ConsentimentoStore,
    PIIAnonymizer,
    PoliticaDeRetencao,
    TratamentoSemBaseLegal,
)


def __getattr__(nome):
    if nome == "ServicoLGPD":
        from contabil_agente.lgpd import ServicoLGPD

        return ServicoLGPD
    raise AttributeError(nome)
