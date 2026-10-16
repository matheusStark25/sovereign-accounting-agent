"""Configuração do robô do FGTS: portal, seletores e tempos.

Os seletores padrão são palpites genéricos e NÃO foram validados contra o portal real da Caixa (o
extrato exige login; o site é protegido e muda). Valide e ajuste por YAML (``FGTS_PORTAL_CONFIG``) ou
variáveis de ambiente antes de usar em produção. O robô nunca tenta resolver captcha nem esconder que é
automação: quando aparece captcha ou tela de login, ele pausa e espera uma pessoa resolver na janela.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple
from urllib.parse import urlparse

import yaml

HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}


class ConfigInvalida(ValueError):
    pass


@dataclass(frozen=True)
class ConfigPortalFGTS:
    url: str = "https://www.caixa.gov.br"
    hosts_permitidos: Tuple[str, ...] = ()  # além do host de ``url``
    seletores_cpf: Tuple[str, ...] = ("input[name='cpf']", "#cpf", "input[id*='cpf']", "input[placeholder*='CPF']", "input[aria-label*='CPF']")
    seletores_envio: Tuple[str, ...] = ("button:has-text('Consultar')", "button:has-text('Buscar')", "button[type='submit']", "input[type='submit']")
    seletores_download: Tuple[str, ...] = ("a[href$='.pdf']", "button:has-text('Baixar PDF')", "button:has-text('Gerar PDF')", "a:has-text('Extrato')")
    seletores_desafio: Tuple[str, ...] = ("iframe[src*='hcaptcha']", "iframe[src*='recaptcha']", "iframe[src*='turnstile']", "[data-sitekey]", "input[type='password']")
    timeout_navegacao_s: int = 60
    timeout_download_s: int = 30
    timeout_humano_s: int = 300
    headless: bool = False  # a pessoa precisa ver a janela para resolver o desafio
    canal: Optional[str] = None  # "msedge" ou "chrome" usam o navegador instalado; None = Chromium do Playwright
    user_data_dir: Optional[str] = None  # perfil persistente (a sessão logada pela pessoa sobrevive entre execuções)
    tamanho_maximo_pdf: int = 25 * 1024 * 1024

    def __post_init__(self) -> None:
        alvo = urlparse(self.url)
        if alvo.scheme not in ("https", "http") or not alvo.hostname:
            raise ConfigInvalida(f"URL inválida: {self.url!r}")
        if alvo.scheme == "http" and alvo.hostname not in HOSTS_LOCAIS:
            raise ConfigInvalida("O portal precisa usar HTTPS (HTTP só é aceito em localhost, para testes).")
        for nome in ("timeout_navegacao_s", "timeout_download_s", "timeout_humano_s"):
            if getattr(self, nome) < 1:
                raise ConfigInvalida(f"{nome} deve ser >= 1.")

    @property
    def hosts(self) -> Tuple[str, ...]:
        return (urlparse(self.url).hostname or "",) + tuple(self.hosts_permitidos)

    @classmethod
    def carregar(cls, origem: Optional[Mapping[str, Any] | str | Path] = None, env: Optional[Mapping[str, str]] = None) -> "ConfigPortalFGTS":
        env = os.environ if env is None else env
        origem = origem if origem is not None else env.get("FGTS_PORTAL_CONFIG")
        dados: dict = {}
        if isinstance(origem, (str, Path)):
            dados = yaml.safe_load(Path(origem).read_text(encoding="utf-8")) or {}
        elif origem:
            dados = dict(origem)
        if env.get("FGTS_CAIXA_URL"):
            dados.setdefault("url", env["FGTS_CAIXA_URL"])
        if env.get("FGTS_BROWSER_USER_DATA_DIR"):
            dados.setdefault("user_data_dir", env["FGTS_BROWSER_USER_DATA_DIR"])
        if env.get("FGTS_BROWSER_CHANNEL"):
            dados.setdefault("canal", env["FGTS_BROWSER_CHANNEL"])
        validos = {f.name for f in fields(cls)}
        desconhecidos = set(dados) - validos
        if desconhecidos:
            raise ConfigInvalida(f"Chaves desconhecidas na configuração do FGTS: {sorted(desconhecidos)}.")
        for nome in ("hosts_permitidos", "seletores_cpf", "seletores_envio", "seletores_download", "seletores_desafio"):
            if nome in dados:
                dados[nome] = tuple(dados[nome])
        return cls(**dados)

    def com(self, **mudancas: Any) -> "ConfigPortalFGTS":
        return replace(self, **mudancas)
