"""RPA com Playwright: extrato do FGTS e do PGMEI, com pausa para a pessoa resolver captcha ou login."""

from .config import ConfigInvalida, ConfigPortalFGTS, ConfigPortalPGMEI
from .humano import HumanoNaoRespondeu, PortaDoHumano, RequerAcaoHumana, hcaptcha_resolvido
from .robo_fgts import ErroDoRobo, PortalBloqueouAutomacao, ResultadoExtrato, RoboExtratoFGTS, SovereignRPAWorker
from .robo_pgmei import RoboExtratoPGMEI

__all__ = [
    "ConfigInvalida", "ConfigPortalFGTS", "ConfigPortalPGMEI", "HumanoNaoRespondeu", "PortaDoHumano", "RequerAcaoHumana",
    "hcaptcha_resolvido", "ErroDoRobo", "PortalBloqueouAutomacao", "ResultadoExtrato", "RoboExtratoFGTS", "RoboExtratoPGMEI", "SovereignRPAWorker",
]
