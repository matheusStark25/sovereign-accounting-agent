"""RPA com Playwright: extrato do FGTS, extrato do PGMEI e consulta de NF-e, CT-e e NFC-e, com pausa para a pessoa resolver captcha ou login."""

from .config import ConfigInvalida, ConfigPortalCTe, ConfigPortalFGTS, ConfigPortalNFCe, ConfigPortalNFe, ConfigPortalPGMEI
from .humano import HumanoNaoRespondeu, PortaDoHumano, RequerAcaoHumana, hcaptcha_resolvido
from .robo_fgts import ErroDoRobo, PortalBloqueouAutomacao, ResultadoExtrato, RoboExtratoFGTS, SovereignRPAWorker
from .robo_nfe import MODELOS, ResultadoNFe, RoboConsultaNFe, config_para_chave, modelo_da_chave
from .robo_pgmei import RoboExtratoPGMEI

__all__ = [
    "ConfigInvalida", "ConfigPortalCTe", "ConfigPortalFGTS", "ConfigPortalNFCe", "ConfigPortalNFe", "ConfigPortalPGMEI", "HumanoNaoRespondeu",
    "PortaDoHumano", "RequerAcaoHumana",
    "hcaptcha_resolvido", "ErroDoRobo", "PortalBloqueouAutomacao", "ResultadoExtrato", "ResultadoNFe", "RoboConsultaNFe", "RoboExtratoFGTS",
    "RoboExtratoPGMEI", "SovereignRPAWorker", "MODELOS", "config_para_chave", "modelo_da_chave",
]
