"""RPA com Playwright: extrato do FGTS com pausa para a pessoa resolver captcha ou login."""

from .config import ConfigInvalida, ConfigPortalFGTS
from .humano import HumanoNaoRespondeu, PortaDoHumano, RequerAcaoHumana
from .robo_fgts import ErroDoRobo, ResultadoExtrato, RoboExtratoFGTS, SovereignRPAWorker

__all__ = [
    "ConfigInvalida", "ConfigPortalFGTS", "HumanoNaoRespondeu", "PortaDoHumano", "RequerAcaoHumana",
    "ErroDoRobo", "ResultadoExtrato", "RoboExtratoFGTS", "SovereignRPAWorker",
]
