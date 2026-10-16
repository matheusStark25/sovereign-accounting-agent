"""Erros explícitos do motor de cálculo.

O motor nunca devolve zero para esconder um erro: ou calcula, ou levanta uma
destas exceções com uma mensagem que diz o que falta.
"""


class CalculoError(Exception):
    """Base de todos os erros do motor de cálculo."""


class DadosInvalidos(CalculoError):
    """Entrada ausente, fora do intervalo ou inconsistente."""


class CompetenciaSemTabela(CalculoError):
    """Não há tabela oficial carregada para a competência pedida."""


class TipoNaoSuportado(CalculoError):
    """Tipo de rescisão ou situação ainda não suportada pelo motor."""
