class ValidacaoError(Exception):
    """Base validation error for IA service."""


class CPFInvalidoError(ValidacaoError):
    pass


class DataInvalidaError(ValidacaoError):
    pass


class ValorInvalidoError(ValidacaoError):
    pass


class RespostaInvalidaError(ValidacaoError):
    pass
