"""Robô do PGMEI (extrato/DAS do MEI), portal público da Receita Federal: CNPJ, hCaptcha e PDF.

É o fluxo que o projeto antigo já rodava (``integracao_gov.py``), agora com as mesmas garantias do robô do FGTS:
só navega nos hosts permitidos, aceita só PDF de verdade, guarda o SHA-256, registra cada passo na trilha WORM e
**para para uma pessoa resolver o hCaptcha** (nunca resolve, nunca esconde que é automação). Sem a pessoa, a
tarefa termina com ``HumanoNaoRespondeu``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from contabil_agente.documentos.validadores import validar_cnpj
from contabil_agente.security.worm_audit import WormAudit

from .config import ConfigPortalPGMEI
from .humano import PortaDoHumano, RequerAcaoHumana, hcaptcha_resolvido
from .robo_fgts import ErroDoRobo, ResultadoExtrato, RoboExtratoFGTS, so_digitos


class RoboExtratoPGMEI(RoboExtratoFGTS):
    PREFIXO = "rpa.pgmei"

    def __init__(
        self,
        config: ConfigPortalPGMEI,
        pasta_de_trabalho,
        audit: Optional[WormAudit] = None,
        tenant: str = "SYSTEM",
        ator: str = "rpa",
        notificar_humano: Optional[Callable[[str, str, Any], None]] = None,
        chave_hash: Optional[str] = None,
    ):
        super().__init__(config, pasta_de_trabalho, audit, tenant, ator, notificar_humano, chave_hash)
        # o hCaptcha continua na tela depois de resolvido: o sinal de "terminou" é o token de resposta preenchido
        self.porta = PortaDoHumano(config.seletores_desafio, config.timeout_humano_s, notificar_humano, resolvido=hcaptcha_resolvido)

    def executar(self, cnpj: str, ano: Optional[int] = None) -> ResultadoExtrato:  # type: ignore[override]
        digitos = so_digitos(cnpj)
        if len(digitos) != 14 or not validar_cnpj(digitos):
            raise ErroDoRobo("cnpj_invalido", "informe 14 dígitos com dígito verificador correto")
        self._passos = []
        self._passo("inicio", titular=self._id_do_titular(digitos), ano=ano or date.today().year)
        try:
            resultado = self.resiliencia.chamar(self._rodar, digitos, ano or date.today().year)
        except RequerAcaoHumana:
            raise
        except Exception as exc:
            self._passo("falha", motivo=getattr(exc, "motivo", type(exc).__name__))
            raise
        self._passo("fim", sha256=resultado.sha256, tamanho=resultado.tamanho)
        resultado.passos = list(self._passos)
        return resultado

    # --------------------------------------------------------------------- fluxo
    def _fluxo(self, page, cnpj: str, ano: int = 0) -> tuple:  # type: ignore[override]
        cfg = self.config
        humano_s = 0.0
        self._checar_host(page)
        self._preencher_cpf(page, cnpj)  # no PGMEI o campo de identificação é o CNPJ
        humano_s += self._pausar_se_desafio(page, "hCaptcha do PGMEI")
        self._clicar_primeiro(page, cfg.seletores_envio, "envio")
        self._aguardar_pagina(page)
        for n, alternativas in enumerate(cfg.navegacao, 1):
            self._clicar_primeiro(page, alternativas, f"navegacao_{n}")
            self._aguardar_pagina(page)
        self._selecionar_ano(page, ano)
        return self._baixar_pdf(page), humano_s + self._humano_extra

    def _aguardar_pagina(self, page) -> None:
        page.wait_for_load_state("domcontentloaded")
        self._checar_host(page)
        self._checar_bloqueio(page)

    def _selecionar_ano(self, page, ano: int) -> None:
        for seletor in self.config.seletores_ano:
            loc = page.locator(seletor)
            try:
                if loc.count() and loc.first.is_visible():
                    loc.first.select_option(label=str(ano))
                    self._passo("ano_selecionado", ano=ano)
                    return
            except Exception:  # noqa: BLE001 - não era este seletor, ou o ano não está na lista
                continue
        try:
            self._clicar_primeiro(page, (f"text={ano}", f"a:has-text('{ano}')"), "ano")
        except ErroDoRobo:
            self._passo("ano_nao_selecionado", ano=ano)  # o portal pode já mostrar o ano certo; o download decide
