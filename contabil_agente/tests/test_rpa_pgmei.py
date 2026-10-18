"""Robô do PGMEI com Playwright de verdade contra um PGMEI falso (mesma estrutura da tela real; hCaptcha resolvido por 'humano')."""

import hashlib
import inspect

import pytest

from contabil_agente.documentos.processador import processar_documento
from contabil_agente.rpa import ConfigInvalida, ConfigPortalPGMEI, ErroDoRobo, HumanoNaoRespondeu, RoboExtratoPGMEI
from contabil_agente.rpa.humano import hcaptcha_resolvido
from contabil_agente.security.worm_audit import WormAudit

from .portal_pgmei_falso import PgmeiFalso
from .test_rpa_fgts import canal  # noqa: F401 - fixture que escolhe o navegador disponível

CNPJ = "11.222.333/0001-81"


@pytest.fixture()
def portal():
    p = PgmeiFalso()
    yield p
    p.parar()


def config(portal, canal, **kw):
    return ConfigPortalPGMEI(url=portal.url, headless=True, canal=canal, timeout_humano_s=20, timeout_navegacao_s=20, timeout_download_s=10, **kw)


def humano_resolvendo(eventos):
    """Faz o papel da pessoa: quando o robô pausa no hCaptcha, resolve (o token de resposta é preenchido)."""
    def notificar(motivo, seletor, page):
        eventos.append((motivo, seletor))
        page.click("#humano-ok")

    return notificar


# ---------------------------------------------------------------- configuração
def test_config_padrao_traz_os_seletores_conferidos_ao_vivo_e_nao_herda_variaveis_do_fgts():
    c = ConfigPortalPGMEI.carregar(env={"FGTS_CAIXA_URL": "https://outro.gov.br", "PGMEI_BROWSER_CHANNEL": "msedge"})
    assert c.hosts[0] == "www8.receita.fazenda.gov.br" and c.canal == "msedge"  # FGTS_CAIXA_URL não vaza para o PGMEI
    assert c.seletores_cpf[0] == "#cnpj" and c.seletores_envio[0] == "#continuar" and c.seletores_desafio[0] == "#hcaptcha"
    with pytest.raises(ConfigInvalida):
        ConfigPortalPGMEI(url="http://www8.receita.fazenda.gov.br")  # HTTPS obrigatório fora do localhost


def test_config_por_yaml_aceita_navegacao_aninhada(tmp_path):
    arq = tmp_path / "pgmei.yaml"
    arq.write_text("navegacao:\n  - ['text=Extrato']\n  - ['text=Anual', 'a:has-text(\"Anual\")']\n", encoding="utf-8")
    assert ConfigPortalPGMEI.carregar(arq).navegacao == (("text=Extrato",), ("text=Anual", 'a:has-text("Anual")'))


def test_sem_extensao_de_captcha_nem_flag_de_evasao_no_codigo():
    import contabil_agente.rpa.config as c
    import contabil_agente.rpa.humano as h
    import contabil_agente.rpa.robo_pgmei as r

    fonte = (inspect.getsource(r) + inspect.getsource(h) + inspect.getsource(c)).lower()
    for proibido in ("buster", "load-extension", "automationcontrolled", "2captcha", "anticaptcha", "stealth", "excludeswitches"):
        assert proibido not in fonte


# ------------------------------------------------------------------ robô de ponta a ponta
def test_fluxo_completo_o_robo_espera_o_humano_resolver_o_hcaptcha_e_baixa_o_pdf_do_ano(portal, canal, tmp_path):
    eventos = []
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    robo = RoboExtratoPGMEI(config(portal, canal), tmp_path / "w", audit, tenant="t1", notificar_humano=humano_resolvendo(eventos), chave_hash="h" * 20)
    r = robo.executar(CNPJ, ano=2026)

    assert eventos and "hCaptcha" in eventos[0][0]  # o robô pausou e chamou a pessoa
    envio = portal.envios[0]
    assert envio["cnpj"].replace(".", "").replace("/", "").replace("-", "") == "11222333000181"
    assert envio["h-captcha-response"].startswith("token-do-captcha")  # só enviou depois de a pessoa resolver
    assert portal.anos_pedidos == ["2026"]  # escolheu o ano na lista
    dados = open(r.caminho, "rb").read()
    assert dados.startswith(b"%PDF-") and hashlib.sha256(dados).hexdigest() == r.sha256
    nomes = [p["passo"] for p in r.passos]
    assert nomes[0] == "inicio" and "humano_resolveu" in nomes and "ano_selecionado" in nomes and nomes[-1] == "fim"


def test_o_pdf_baixado_passa_pelo_leitor_e_e_classificado_como_das(portal, canal, tmp_path):
    r = RoboExtratoPGMEI(config(portal, canal), tmp_path, notificar_humano=humano_resolvendo([])).executar(CNPJ, ano=2025)
    res = processar_documento(r.caminho)
    assert res.tipo == "DAS" and res.sha256 == r.sha256
    assert portal.anos_pedidos == ["2025"]


def test_trilha_usa_prefixo_pgmei_e_nao_guarda_o_cnpj(portal, canal, tmp_path):
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    RoboExtratoPGMEI(config(portal, canal), tmp_path / "w", audit, tenant="t1", notificar_humano=humano_resolvendo([]), chave_hash="h" * 20).executar(CNPJ)
    bruto = (tmp_path / "audit" / "t1.worm.jsonl").read_text(encoding="utf-8")
    assert "rpa.pgmei.pdf_salvo" in bruto and "rpa.fgts" not in bruto
    assert "11222333000181" not in bruto and CNPJ not in bruto and audit.verificar("t1").ok


def test_ninguem_resolve_o_captcha_o_robo_para_e_nao_envia_nada(portal, canal, tmp_path):
    cfg = config(portal, canal).com(timeout_humano_s=3)
    with pytest.raises(HumanoNaoRespondeu):
        RoboExtratoPGMEI(cfg, tmp_path, notificar_humano=lambda m, s, page: None).executar(CNPJ)
    assert portal.envios == []  # sem a pessoa, o formulário nem foi enviado


def test_cnpj_invalido_nem_abre_o_navegador(portal, canal, tmp_path):
    robo = RoboExtratoPGMEI(config(portal, canal), tmp_path)
    for ruim in ("123", "11.222.333/0001-82", "52998224725"):
        with pytest.raises(ErroDoRobo) as e:
            robo.executar(ruim)
        assert e.value.motivo == "cnpj_invalido"
    assert portal.envios == []


def test_download_que_nao_e_pdf_e_recusado(canal, tmp_path):
    p = PgmeiFalso(download_malicioso=True)
    try:
        with pytest.raises(ErroDoRobo) as e:
            RoboExtratoPGMEI(config(p, canal), tmp_path, notificar_humano=humano_resolvendo([])).executar(CNPJ)
        assert e.value.motivo == "download_nao_e_pdf"
    finally:
        p.parar()


def test_etapa_nao_encontrada_diz_qual_e_o_que_ajustar(portal, canal, tmp_path):
    cfg = config(portal, canal, navegacao=(("text=Item que nao existe",),), espera_elemento_s=2, ajuda_humana=False)
    with pytest.raises(ErroDoRobo) as e:
        RoboExtratoPGMEI(cfg, tmp_path, notificar_humano=humano_resolvendo([])).executar(CNPJ)
    assert e.value.motivo == "botao_navegacao_1_nao_encontrado"


def test_hcaptcha_resolvido_so_com_token_preenchido(portal, canal, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(channel=canal, headless=True)
        try:
            page = b.new_page()
            page.goto(portal.url)
            assert hcaptcha_resolvido(page) is False  # o widget está na tela, mas ninguém resolveu
            page.click("#humano-ok")
            assert hcaptcha_resolvido(page) is True
        finally:
            b.close()
