"""Configuração do robô do FGTS: portal, seletores e tempos.

Os seletores padrão são palpites genéricos e NÃO foram validados contra o portal real da Caixa (o
extrato exige login; o site é protegido e muda). Valide e ajuste por YAML (``FGTS_PORTAL_CONFIG``) ou
variáveis de ambiente antes de usar em produção. O robô nunca tenta resolver captcha nem esconder que é
automação: quando aparece captcha ou tela de login, ele pausa e espera uma pessoa resolver na janela.
"""

from __future__ import annotations

import os
import re
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
    # nomes das variáveis de ambiente que cada portal lê (as subclasses trocam; vazio = não lê)
    ENV_PORTAL = "FGTS_PORTAL_CONFIG"
    ENV_URL = "FGTS_CAIXA_URL"
    ENV_PERFIL = "FGTS_BROWSER_USER_DATA_DIR"
    ENV_CANAL = "FGTS_BROWSER_CHANNEL"

    timeout_navegacao_s: int = 60
    timeout_download_s: int = 30
    timeout_humano_s: int = 300
    headless: bool = False  # a pessoa precisa ver a janela para resolver o desafio
    canal: Optional[str] = None  # "msedge" ou "chrome" usam o navegador instalado; None = Chromium do Playwright
    user_data_dir: Optional[str] = None  # perfil persistente (a sessão logada pela pessoa sobrevive entre execuções)
    tamanho_maximo_pdf: int = 25 * 1024 * 1024
    # Se os seletores acima não acharem nada (o portal mudou), o robô procura pelo que o elemento é: rótulo, texto, papel.
    rotulo_campo: str = r"cpf|cnpj|nis|pis|inscri"
    rotulo_envio: str = r"consultar|continuar|buscar|pesquisar|avan[cç]ar|enviar|acessar|emitir"
    rotulo_download: str = r"baixar|download|gerar pdf|imprimir|pdf|extrato"
    espera_elemento_s: int = 15  # quanto esperar um elemento aparecer (páginas lentas ou que montam a tela por JavaScript)
    ajuda_humana: bool = True  # não achou? mostra um aviso na janela e espera a pessoa fazer a etapa, em vez de abortar
    capturar_tela_na_falha: bool = False  # a captura pode mostrar dados pessoais; a estrutura mascarada é sempre salva

    def __post_init__(self) -> None:
        alvo = urlparse(self.url)
        if alvo.scheme not in ("https", "http") or not alvo.hostname:
            raise ConfigInvalida(f"URL inválida: {self.url!r}")
        if alvo.scheme == "http" and alvo.hostname not in HOSTS_LOCAIS:
            raise ConfigInvalida("O portal precisa usar HTTPS (HTTP só é aceito em localhost, para testes).")
        for nome in ("timeout_navegacao_s", "timeout_download_s", "timeout_humano_s", "espera_elemento_s"):
            if getattr(self, nome) < 1:
                raise ConfigInvalida(f"{nome} deve ser >= 1.")
        for nome in ("rotulo_campo", "rotulo_envio", "rotulo_download"):
            try:
                re.compile(getattr(self, nome))
            except re.error as exc:
                raise ConfigInvalida(f"{nome} não é uma expressão regular válida: {exc}") from exc

    @property
    def hosts(self) -> Tuple[str, ...]:
        return (urlparse(self.url).hostname or "",) + tuple(self.hosts_permitidos)

    @classmethod
    def carregar(cls, origem: Optional[Mapping[str, Any] | str | Path] = None, env: Optional[Mapping[str, str]] = None) -> "ConfigPortalFGTS":
        env = os.environ if env is None else env
        origem = origem if origem is not None else env.get(cls.ENV_PORTAL)
        dados: dict = {}
        if isinstance(origem, (str, Path)):
            dados = yaml.safe_load(Path(origem).read_text(encoding="utf-8")) or {}
        elif origem:
            dados = dict(origem)
        if cls.ENV_URL and env.get(cls.ENV_URL):
            dados.setdefault("url", env[cls.ENV_URL])
        if cls.ENV_PERFIL and env.get(cls.ENV_PERFIL):
            dados.setdefault("user_data_dir", env[cls.ENV_PERFIL])
        if cls.ENV_CANAL and env.get(cls.ENV_CANAL):
            dados.setdefault("canal", env[cls.ENV_CANAL])
        validos = {f.name for f in fields(cls)}
        desconhecidos = set(dados) - validos
        if desconhecidos:
            raise ConfigInvalida(f"Chaves desconhecidas na configuração do FGTS: {sorted(desconhecidos)}.")
        for nome, valor in list(dados.items()):
            if isinstance(valor, list):  # YAML traz listas; a configuração é imutável (tuplas, inclusive aninhadas)
                dados[nome] = tuple(tuple(v) if isinstance(v, list) else v for v in valor)
        return cls(**dados)

    def com(self, **mudancas: Any) -> "ConfigPortalFGTS":
        return replace(self, **mudancas)


@dataclass(frozen=True)
class ConfigPortalPGMEI(ConfigPortalFGTS):
    """PGMEI (DAS do MEI), portal público da Receita Federal: CNPJ, hCaptcha resolvido por uma pessoa e o extrato em PDF.

    Conferido ao vivo em 2026-10-17 (antes do captcha): campo ``#cnpj``, widget ``#hcaptcha`` (com iframe do hcaptcha.com)
    e botão ``#continuar``. As etapas depois do captcha (``navegacao``, ``seletores_ano`` e ``seletores_download``) vêm
    do robô que já rodava no projeto antigo e só se confirmam com uma pessoa resolvendo o captcha: se o portal mudou,
    o robô para dizendo qual etapa não achou, e ``python -m agente_v2.cli calibrar-fgts --url <esta url>`` grava as
    telas reais para ajustar ``PGMEI_PORTAL_CONFIG``.
    """

    ENV_PORTAL = "PGMEI_PORTAL_CONFIG"
    ENV_URL = ""
    ENV_PERFIL = "PGMEI_BROWSER_USER_DATA_DIR"
    ENV_CANAL = "PGMEI_BROWSER_CHANNEL"

    url: str = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/Identificacao"
    seletores_cpf: Tuple[str, ...] = ("#cnpj", "input[name='cnpj']")  # o campo de identificação, que no PGMEI é o CNPJ
    seletores_envio: Tuple[str, ...] = ("#continuar", "button:has-text('Continuar')", "button[type='submit']")
    seletores_desafio: Tuple[str, ...] = ("#hcaptcha", "iframe[src*='hcaptcha']", "[data-sitekey]")
    seletores_download: Tuple[str, ...] = ("button:has-text('Gerar PDF')", "a:has-text('Gerar PDF')", "button:has-text('Download')",
                                           "a:has-text('Download')", "a[href$='.pdf']")
    navegacao: Tuple[Tuple[str, ...], ...] = (("text=Pagamentos", "a:has-text('Pagamentos')", "text=Extratos"),)  # cada item: alternativas de UM clique
    seletores_ano: Tuple[str, ...] = ("select", "[role='combobox']")
