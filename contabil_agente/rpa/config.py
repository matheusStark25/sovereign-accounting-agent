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


@dataclass(frozen=True)
class ConfigPortalNFe(ConfigPortalFGTS):
    """Consulta pública de NF-e (resumo), portal nacional da NF-e (SEFAZ): chave de acesso, hCaptcha resolvido por uma pessoa.

    Conferido ao vivo em 2026-10-19 (antes do captcha): campo ``#ctl00_ContentPlaceHolder1_txtChaveAcessoResumo``, botão
    ``#ctl00_ContentPlaceHolder1_btnConsultarHCaptcha`` (postback ASP.NET) e o hCaptcha como caixa de seleção visível assim
    que a página abre, com o ``textarea[name='h-captcha-response']``. A tela da nota que aparece depois do captcha só se
    confirma com uma pessoa resolvendo-o numa consulta real: o robô a lê por rótulos (``<label>``, ``<th>``, ``<dt>`` ou
    linhas ``Rótulo: valor``) e, se o portal mudou, para dizendo o que não achou e salva a estrutura mascarada da tela
    (``diagnostico_*.json``) para ajustar ``NFE_PORTAL_CONFIG``.
    """

    ENV_PORTAL = "NFE_PORTAL_CONFIG"
    ENV_URL = ""
    ENV_PERFIL = "NFE_BROWSER_USER_DATA_DIR"
    ENV_CANAL = "NFE_BROWSER_CHANNEL"

    url: str = "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=resumo&tipoConteudo=7PhJ+gAVw2g="
    seletores_cpf: Tuple[str, ...] = ("#ctl00_ContentPlaceHolder1_txtChaveAcessoResumo", "input[id$='txtChaveAcessoResumo']", "input[id*='ChaveAcesso']")
    seletores_envio: Tuple[str, ...] = ("#ctl00_ContentPlaceHolder1_btnConsultarHCaptcha", "input[id$='btnConsultarHCaptcha']", "input[value='Continuar']")
    seletores_desafio: Tuple[str, ...] = ("iframe[src*='hcaptcha']", "iframe[title*='hCaptcha' i]", "[data-sitekey]")
    rotulo_campo: str = r"chave|acesso"
    # a tela da nota: o robô a reconhece pela chave na tela ou por estes títulos
    padrao_resultado: str = r"dados da nf-?e|situa[cç][aã]o atual"
    padrao_nota_inexistente: str = r"nf-?e (n[aã]o encontrada|inexistente)|chave de acesso (inv[aá]lida|n[aã]o encontrada)|n[aã]o existe nf-?e"
    espera_resultado_s: int = 25  # quanto esperar a tela da nota depois de clicar em "Continuar"
    tentativas_captcha: int = 3  # o token do hCaptcha vence: se o portal devolver o formulário, a pessoa resolve de novo
    modelos: Tuple[str, ...] = ("55",)  # modelo do documento na chave (posições 21-22): 55 NF-e, 57 CT-e, 65 NFC-e
    nome_portal: str = "portal nacional da NF-e (consulta pública, resumo)"
    # captcha de imagem (a pessoa digita o código): o robô mostra o aviso na janela e espera "Terminei esta etapa"
    seletores_captcha_imagem: Tuple[str, ...] = ()
    uf: str = ""  # código IBGE da UF atendida (portais estaduais, como o da NFC-e); vazio = nacional

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.espera_resultado_s < 1 or self.tentativas_captcha < 1:
            raise ConfigInvalida("espera_resultado_s e tentativas_captcha devem ser >= 1.")
        for nome in ("padrao_resultado", "padrao_nota_inexistente"):
            try:
                re.compile(getattr(self, nome))
            except re.error as exc:
                raise ConfigInvalida(f"{nome} não é uma expressão regular válida: {exc}") from exc


@dataclass(frozen=True)
class ConfigPortalCTe(ConfigPortalNFe):
    """Consulta pública de CT-e (resumo), portal nacional do CT-e. Conferido ao vivo em 2026-10-19: a mesma tela da NF-e
    (``#ctl00_ContentPlaceHolder1_txtChaveAcessoResumo``, ``#ctl00_ContentPlaceHolder1_btnConsultarHCaptcha`` e hCaptcha visível)."""

    ENV_PORTAL = "CTE_PORTAL_CONFIG"
    ENV_PERFIL = "CTE_BROWSER_USER_DATA_DIR"
    ENV_CANAL = "CTE_BROWSER_CHANNEL"

    url: str = "https://www.cte.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=resumo&tipoConteudo=cktLvUUKqh0="
    padrao_resultado: str = r"dados do ct-?e|situa[cç][aã]o atual"
    padrao_nota_inexistente: str = r"ct-?e (n[aã]o encontrado|inexistente)|chave de acesso (inv[aá]lida|n[aã]o encontrada)|n[aã]o existe ct-?e"
    modelos: Tuple[str, ...] = ("57",)
    nome_portal: str = "portal nacional do CT-e (consulta pública, resumo)"


@dataclass(frozen=True)
class ConfigPortalNFCe(ConfigPortalNFe):
    """Consulta pública de NFC-e, que é estadual. O padrão é a SEFAZ-SP, conferida ao vivo em 2026-10-19: campo
    ``#Conteudo_txtChaveAcesso``, código de imagem ``#txCodigo`` (a pessoa digita) e botão ``#Conteudo_btnConsultaResumida``.
    Para outra UF, ``NFCE_PORTAL_CONFIG`` com a ``url`` da consulta da sua SEFAZ, a ``uf`` (código IBGE) e os seletores."""

    ENV_PORTAL = "NFCE_PORTAL_CONFIG"
    ENV_PERFIL = "NFCE_BROWSER_USER_DATA_DIR"
    ENV_CANAL = "NFCE_BROWSER_CHANNEL"

    url: str = "https://www.nfce.fazenda.sp.gov.br/NFCeConsultaPublica/Paginas/ConsultaPublica.aspx"
    seletores_cpf: Tuple[str, ...] = ("#Conteudo_txtChaveAcesso", "input[id$='txtChaveAcesso']")
    seletores_envio: Tuple[str, ...] = ("#Conteudo_btnConsultaResumida", "input[id$='btnConsultaResumida']")
    seletores_captcha_imagem: Tuple[str, ...] = ("#txCodigo",)
    padrao_resultado: str = r"dados da nfc-?e|situa[cç][aã]o atual|dados do emitente"
    padrao_nota_inexistente: str = r"nfc-?e (n[aã]o encontrada|inexistente)|chave de acesso (inv[aá]lida|n[aã]o encontrada)|n[aã]o existe nfc-?e"
    modelos: Tuple[str, ...] = ("65",)
    nome_portal: str = "SEFAZ-SP (consulta pública de NFC-e)"
    uf: str = "35"
