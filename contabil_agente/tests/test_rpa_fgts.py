"""Robô do FGTS com Playwright de verdade contra um portal falso local (captcha de mentira resolvido por 'humano')."""

import hashlib
import shutil

import pytest

from contabil_agente.documentos.processador import processar_documento
from contabil_agente.rpa import (
    ConfigInvalida,
    ConfigPortalFGTS,
    ErroDoRobo,
    HumanoNaoRespondeu,
    PortaDoHumano,
    RoboExtratoFGTS,
    SovereignRPAWorker,
)
from contabil_agente.security.worm_audit import WormAudit

from .portal_fgts_falso import PortalFalso, pdf_extrato

CPF = "529.982.247-25"


def navegador_disponivel() -> str | None:
    """'msedge' ou 'chrome' se o Playwright conseguir abrir um deles; 'chromium' se o do Playwright estiver instalado."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        for canal in ("msedge", "chrome", None):
            try:
                b = p.chromium.launch(channel=canal, headless=True)
                b.close()
                return canal or "chromium"
            except Exception:  # noqa: BLE001
                continue
    return None


@pytest.fixture(scope="module")
def canal():
    try:
        c = navegador_disponivel()
    except Exception:  # noqa: BLE001
        c = None
    if c is None:
        pytest.skip("Nenhum navegador disponível para o Playwright (Edge, Chrome ou Chromium).")
    return None if c == "chromium" else c


@pytest.fixture()
def portal():
    p = PortalFalso()
    yield p
    p.parar()


def config(portal, canal, **kw):
    return ConfigPortalFGTS(url=portal.url, headless=True, canal=canal, timeout_humano_s=20, timeout_navegacao_s=20, timeout_download_s=10, **kw)


def humano_clicando(eventos):
    """Faz o papel da pessoa: quando o robô pausa, clica no 'Não sou um robô'."""
    def notificar(motivo, seletor, page):
        eventos.append((motivo, seletor))
        page.click("#humano-ok")

    return notificar


# ---------------------------------------------------------------- configuração
def test_config_https_obrigatorio_fora_do_localhost():
    with pytest.raises(ConfigInvalida):
        ConfigPortalFGTS(url="http://portal.exemplo.com")
    with pytest.raises(ConfigInvalida):
        ConfigPortalFGTS(url="ftp://x")
    assert ConfigPortalFGTS(url="http://127.0.0.1:8000").hosts[0] == "127.0.0.1"


def test_config_por_yaml_e_ambiente(tmp_path):
    arq = tmp_path / "fgts.yaml"
    arq.write_text("url: https://portal.exemplo.com\ntimeout_humano_s: 99\nseletores_cpf: ['#meu-cpf']\n", encoding="utf-8")
    c = ConfigPortalFGTS.carregar(arq)
    assert c.timeout_humano_s == 99 and c.seletores_cpf == ("#meu-cpf",)
    assert ConfigPortalFGTS.carregar(env={"FGTS_CAIXA_URL": "https://x.gov.br", "FGTS_BROWSER_CHANNEL": "msedge"}).canal == "msedge"
    with pytest.raises(ConfigInvalida):
        ConfigPortalFGTS.carregar({"inventada": 1})


def test_nao_ha_extensao_de_captcha_nem_flag_de_evasao_no_codigo():
    import contabil_agente.rpa.robo_fgts as r
    import inspect

    fonte = inspect.getsource(r).lower()
    for proibido in ("buster", "load-extension", "automationcontrolled", "2captcha", "anticaptcha", "stealth"):
        assert proibido not in fonte


# ------------------------------------------------------------------ robô de ponta a ponta
def test_fluxo_completo_com_o_humano_resolvendo_o_captcha(portal, canal, tmp_path):
    eventos = []
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    robo = RoboExtratoFGTS(config(portal, canal), tmp_path / "w", audit, tenant="t1", notificar_humano=humano_clicando(eventos), chave_hash="h" * 20)
    r = robo.executar(CPF)
    assert eventos and "captcha" in eventos[0][0] or "desafio" in eventos[0][0]
    assert r.segundos_com_humano >= 0 and r.tamanho > 100
    dados = open(r.caminho, "rb").read()
    assert dados.startswith(b"%PDF-") and hashlib.sha256(dados).hexdigest() == r.sha256
    assert any("52998224725" in c for c in portal.cpfs_recebidos)  # o CPF chegou ao portal
    nomes = [p["passo"] for p in r.passos]
    assert nomes[0] == "inicio" and "humano_resolveu" in nomes and nomes[-1] == "fim" and "pdf_salvo" in nomes


def test_cpf_nunca_aparece_na_trilha_so_o_hash(portal, canal, tmp_path):
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    RoboExtratoFGTS(config(portal, canal), tmp_path / "w", audit, tenant="t1", notificar_humano=humano_clicando([]), chave_hash="h" * 20).executar(CPF)
    bruto = (tmp_path / "audit" / "t1.worm.jsonl").read_text(encoding="utf-8")
    assert "52998224725" not in bruto and CPF not in bruto and "rpa.fgts.pdf_salvo" in bruto and audit.verificar("t1").ok


def test_sem_captcha_nao_pausa(canal, tmp_path):
    p = PortalFalso(com_captcha=False)
    try:
        eventos = []
        r = RoboExtratoFGTS(config(p, canal), tmp_path, notificar_humano=humano_clicando(eventos)).executar(CPF)
        assert eventos == [] and r.segundos_com_humano == 0
    finally:
        p.parar()


def test_ninguem_resolve_o_captcha_o_robo_para_com_erro_claro(portal, canal, tmp_path):
    cfg = config(portal, canal).com(timeout_humano_s=3)
    with pytest.raises(HumanoNaoRespondeu):
        RoboExtratoFGTS(cfg, tmp_path, notificar_humano=lambda m, s, page: None).executar(CPF)
    assert not list((tmp_path / "downloads").glob("*")) if (tmp_path / "downloads").exists() else True


def test_download_que_nao_e_pdf_e_recusado(canal, tmp_path):
    p = PortalFalso(com_captcha=False, download_malicioso=True)
    try:
        with pytest.raises(ErroDoRobo) as e:
            RoboExtratoFGTS(config(p, canal), tmp_path).executar(CPF)
        assert e.value.motivo == "download_nao_e_pdf"
        assert not list((tmp_path / "downloads").glob("*.pdf")) if (tmp_path / "downloads").exists() else True
    finally:
        p.parar()


def test_redirecionamento_para_outro_dominio_e_bloqueado_antes_de_enviar_o_cpf(canal, tmp_path):
    destino = PortalFalso(com_captcha=False)  # outro "domínio": localhost em vez de 127.0.0.1
    p = PortalFalso(redireciona=destino.url.replace("127.0.0.1", "localhost"))
    try:
        robo = RoboExtratoFGTS(config(p, canal), tmp_path)
        with pytest.raises(ErroDoRobo) as e:
            robo.executar(CPF)
        assert e.value.motivo == "dominio_nao_permitido"
        assert any(passo["passo"] == "dominio_nao_permitido" for passo in robo._passos)
        assert destino.cpfs_recebidos == [] and p.cpfs_recebidos == []
    finally:
        p.parar()
        destino.parar()


def test_cpf_invalido_nem_abre_o_navegador(portal, canal, tmp_path):
    robo = RoboExtratoFGTS(config(portal, canal), tmp_path)
    for ruim in ("123", "111.111.111-11", "529.982.247-24", ""):
        with pytest.raises(ErroDoRobo) as e:
            robo.executar(ruim)
        assert e.value.motivo == "cpf_invalido"
    assert portal.cpfs_recebidos == []


def test_seletor_errado_pede_ajuste_de_configuracao(canal, tmp_path):
    p = PortalFalso(com_captcha=False)
    try:
        cfg = config(p, canal).com(seletores_cpf=("#nao-existe",))
        with pytest.raises(ErroDoRobo) as e:
            RoboExtratoFGTS(cfg, tmp_path).executar(CPF)
        assert e.value.motivo == "campo_cpf_nao_encontrado"
    finally:
        p.parar()


def test_portal_fora_do_ar_vira_erro_e_o_disjuntor_abre_e_para_de_tentar(tmp_path, canal):
    import time

    from contabil_agente.resilience import CircuitoAberto

    p = PortalFalso()
    url = p.url
    p.parar()
    cfg = ConfigPortalFGTS(url=url, headless=True, canal=canal, timeout_navegacao_s=3)
    robo = RoboExtratoFGTS(cfg, tmp_path)
    robo.resiliencia._dormir = lambda s: None
    with pytest.raises(ErroDoRobo) as e:
        robo.executar(CPF)
    assert e.value.motivo in ("portal_inacessivel", "navegador_indisponivel")
    with pytest.raises((ErroDoRobo, CircuitoAberto)):
        robo.executar(CPF)  # a 3ª falha seguida abre o disjuntor
    inicio = time.monotonic()
    with pytest.raises(CircuitoAberto):
        robo.executar(CPF)
    assert time.monotonic() - inicio < 2  # recusou sem abrir o navegador


def test_extrato_baixado_passa_pelo_leitor_de_documentos(portal, canal, tmp_path):
    r = RoboExtratoFGTS(config(portal, canal), tmp_path, notificar_humano=humano_clicando([])).executar(CPF)
    doc = processar_documento(r.caminho)
    assert doc.tipo == "FGTS_EXTRATO" and doc.extracted_data["saldo"] == "12000.00" and doc.sha256 == r.sha256


# --------------------------------------------------------------- porta do humano
class PaginaFalsa:
    """Só o suficiente de uma página para testar a espera sem navegador."""

    def __init__(self, visivel_ate):
        self.chamadas, self.visivel_ate = 0, visivel_ate

    def locator(self, seletor):
        pagina = self

        class L:
            first = property(lambda s: s)

            def count(s):
                return 1 if pagina.chamadas < pagina.visivel_ate else 0

            def is_visible(s):
                return pagina.chamadas < pagina.visivel_ate

        return L()

    def wait_for_timeout(self, ms):
        self.chamadas += 1


def test_porta_do_humano_notifica_espera_e_devolve_o_tempo():
    tempo = iter(range(0, 100))
    avisos = []
    porta = PortaDoHumano(["[data-sitekey]"], timeout_s=30, notificar=lambda m, s, p: avisos.append((m, s)), relogio=lambda: next(tempo))
    assert porta.esperar(PaginaFalsa(visivel_ate=3), "captcha") > 0 and avisos == [("captcha", "[data-sitekey]")]


def test_porta_sem_desafio_nao_notifica():
    avisos = []
    porta = PortaDoHumano(["[data-sitekey]"], notificar=lambda *a: avisos.append(a))
    assert porta.esperar(PaginaFalsa(visivel_ate=0), "x") == 0.0 and avisos == []


def test_porta_estoura_o_prazo():
    tempo = iter(range(0, 1000, 10))
    porta = PortaDoHumano(["x"], timeout_s=25, relogio=lambda: next(tempo))
    with pytest.raises(HumanoNaoRespondeu):
        porta.esperar(PaginaFalsa(visivel_ate=10**6), "captcha")


# ------------------------------------------------------------ interface antiga
def test_worker_antigo_continua_com_a_mesma_interface(portal, canal, tmp_path):
    w = SovereignRPAWorker("sessao-1", tmp_path, {"url": portal.url, "headless": True, "canal": canal, "timeout_humano_s": 3})
    with w:
        r = w.executar("extrato_fgts", {"cpf": CPF})
        assert r["status"] == "error" and r["reason"] == "captcha_nao_resolvido"
        assert w.executar("outra_coisa", {})["reason"].startswith("tarefa_nao_suportada")
