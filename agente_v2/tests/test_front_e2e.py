"""Front-end de ponta a ponta: servidor uvicorn real + navegador real (Playwright). Pula se não houver navegador."""

import re
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from agente_v2.main import create_app
from contabil_agente.chat import ChatEngine, ChatStore
from contabil_agente.security.auth import AuthService, AuthSettings
from contabil_agente.security.rbac_manager import RBACManager

from .test_api import nova_auditoria, novo_dispatcher

SENHA = "Senha-Forte-123"
WEB = Path(__file__).resolve().parents[1] / "web"
APP = {}  # o app do servidor de teste, para os testes de voz trocarem o STT e o consentimento
FALA = Path(__file__).resolve().parents[2] / "contabil_agente" / "tests" / "dados" / "fala_calcular_rescisao.wav"


def navegador():
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    for canal in ("msedge", "chrome", None):
        try:
            return p, p.chromium.launch(channel=canal, headless=True)
        except Exception:  # noqa: BLE001
            continue
    p.stop()
    return None, None


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    import os

    os.environ.update({"DATA_DIR": str(tmp / "dados"), "AGENTE_ENV": "dev"})
    auth = AuthService(AuthSettings(secret="s" * 40, db_path=str(tmp / "auth.db")), rbac=RBACManager())
    auth.criar_usuario("maria", SENHA, "empresa_a", ["accountant"])
    app = create_app(auth=auth, engine=ChatEngine(llm=None), store=ChatStore(str(tmp / "chat.db")), audit=nova_auditoria(tmp), dispatcher=novo_dispatcher(tmp))
    APP["app"] = app
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{porta}"
    srv.should_exit = True
    t.join(5)


@pytest.fixture(scope="module")
def browser():
    p, b = navegador()
    if b is None:
        pytest.skip("Nenhum navegador disponível para o Playwright.")
    APP["pw"] = p  # um só Playwright por processo: o navegador do microfone sai do mesmo
    yield b
    b.close()
    p.stop()


@pytest.fixture()
def pagina(browser, servidor):
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, accept_downloads=True)  # tamanho de celular
    page = ctx.new_page()
    page.erros = []
    page.on("console", lambda m: page.erros.append(m.text) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: page.erros.append(str(e)))
    page.goto(servidor)
    yield page
    ctx.close()


def entrar(page, usuario="maria", senha=SENHA):
    page.fill("#usuario", usuario)
    page.fill("#senha", senha)
    page.click("#botao-entrar")


def ultima_resposta(page, quantas=2):
    """Espera a resposta de número ``quantas`` (a 1ª é a boas-vindas) e o fim do "digitando". Sem eval: a CSP da página o proíbe."""
    page.locator("#mensagens .msg.ela").nth(quantas - 1).wait_for(timeout=15000)
    page.locator("#mensagens .digitando").wait_for(state="detached", timeout=15000)
    return page.locator("#mensagens .msg.ela").nth(quantas - 1).inner_text()


def test_login_com_senha_errada_mostra_erro_e_nao_entra(pagina):
    entrar(pagina, senha="errada-Errada-1")
    pagina.wait_for_selector("#erro-login:not([hidden])")
    assert "inválid" in pagina.inner_text("#erro-login") and pagina.is_hidden("#app")


def test_login_chat_calculo_e_pdf(pagina):
    entrar(pagina)
    pagina.wait_for_selector("#app:not([hidden])")
    assert "maria" in pagina.inner_text("#quem") or pagina.is_hidden("#quem")  # em tela estreita o nome fica oculto
    pagina.click(".chip[data-texto='Calcular INSS']")
    assert "salário" in ultima_resposta(pagina).lower()
    pagina.fill("#texto", "salário de R$ 5.000,00")
    pagina.press("#texto", "Enter")
    texto = ultima_resposta(pagina, 3)
    assert "R$ 501,51" in texto
    with pagina.expect_download() as d:
        pagina.click("text=Baixar PDF do cálculo")
    caminho = d.value.path()
    assert open(caminho, "rb").read(5) == b"%PDF-"


def test_upload_de_documento_mostra_cartao_com_alertas(pagina):
    entrar(pagina)
    pagina.wait_for_selector("#app:not([hidden])")
    holerite = ("HOLERITE - Competência: 09/2026\nCNPJ 11.222.333/0001-81\nSalário base 6.000,00\nTotal de proventos 6.000,00\n"
                "INSS 700,00\nIRRF 385,10\nTotal de descontos 1.085,10\nFGTS 480,00\nLíquido a receber 4.914,90\n")
    pagina.set_input_files("#arquivo", files=[{"name": "holerite.txt", "mimeType": "text/plain", "buffer": holerite.encode()}])
    pagina.wait_for_selector(".doc", timeout=15000)
    cartao = pagina.inner_text(".doc").replace(" ", " ")  # o navegador usa espaço sem quebra depois de R$.replace(" ", " ")  # o navegador usa espaço sem quebra depois de R$
    assert "Holerite" in cartao and "R$ 6.000,00" in cartao and "recalculado 641.51" in cartao
    assert pagina.locator(".doc .selo.aviso").count() == 1
    # o alerta é parte do fluxo normal da página (não flutua sobre ela como um toast)
    assert pagina.eval_on_selector(".doc .alerta", "e => getComputedStyle(e).position") != "fixed"


def test_painel_e_sair(pagina):
    entrar(pagina)
    pagina.wait_for_selector("#app:not([hidden])")
    pagina.click("button[data-aba='painel']")
    assert pagina.is_visible("#form-fgts") and "Nenhuma decisão" in pagina.inner_text("#lista-pendentes") or pagina.is_visible("#lista-pendentes")
    assert pagina.is_disabled("#consentimento-ia")  # contador não altera o consentimento de sistema
    pagina.click("#botao-sair")
    pagina.wait_for_selector("#tela-login:not([hidden])")
    assert pagina.evaluate("() => sessionStorage.getItem('mh_token')") is None


def test_sem_erros_de_console_nem_violacao_de_csp(pagina):
    entrar(pagina)
    pagina.wait_for_selector("#app:not([hidden])")
    pagina.fill("#texto", "oi")
    pagina.press("#texto", "Enter")
    pagina.wait_for_timeout(800)
    relevantes = [e for e in pagina.erros if "401" not in e]
    assert relevantes == [], relevantes


def test_pagina_nao_carrega_nada_de_fora_nem_usa_innerhtml():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "app.css").read_text(encoding="utf-8")
    for fonte in (html, js, css):
        assert not re.search(r"https?://(?!www\.w3\.org)", fonte), "o front não pode depender de recursos externos (CSP default-src 'self')"
    assert "innerHTML" not in js and "eval(" not in js and "document.write" not in js
    assert not re.search(r"\son\w+\s*=", html) and "<script>" not in html  # nada de JS inline


# ------------------------------------------------------------------------------ voz (microfone de verdade, com uma fala gravada)
@pytest.fixture(scope="module")
def browser_com_microfone(browser):
    """Navegador cujo "microfone" toca o arquivo ``fala_calcular_rescisao.wav`` (flags de teste do Chromium para o NOSSO app local)."""
    p = APP["pw"]
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-audio-capture={FALA}"]
    for canal in ("msedge", "chrome", None):
        try:
            b = p.chromium.launch(channel=canal, headless=True, args=args)
            break
        except Exception:  # noqa: BLE001
            continue
    else:
        pytest.skip("Nenhum navegador disponível para o Playwright.")
    yield b
    b.close()


@pytest.fixture()
def pagina_microfone(browser_com_microfone, servidor):
    APP["app"].state.lgpd.registrar_consentimento("empresa_a", None, "envio_a_provedor_de_ia", True, "e2e")
    ctx = browser_com_microfone.new_context(viewport={"width": 390, "height": 800}, permissions=["microphone"])
    page = ctx.new_page()
    page.erros = []
    page.on("pageerror", lambda e: page.erros.append(str(e)))
    page.goto(servidor)
    yield page
    ctx.close()
    APP["app"].state.stt = None


class STTDoTeste:
    """Devolve o texto combinado e guarda o que o navegador mandou: prova que o áudio do microfone subiu pelo WebSocket."""

    def __init__(self, texto="calcular INSS"):
        self.texto, self.recebidos = texto, []

    def transcrever(self, audio, nome="fala.webm", idioma="pt"):
        self.recebidos.append((len(audio), nome, idioma))
        return self.texto


def gravar_e_enviar(pagina, segundos=2.8):
    pagina.click("#botao-voz")
    pagina.wait_for_selector("#botao-voz.gravando")
    pagina.wait_for_timeout(int(segundos * 1000))  # a fala dura ~2,4 s
    pagina.click("#botao-voz")


def test_microfone_grava_envia_pelo_websocket_e_a_resposta_aparece_na_conversa(pagina_microfone):
    stt = STTDoTeste("calcular INSS")
    APP["app"].state.stt = stt
    entrar(pagina_microfone)
    pagina_microfone.wait_for_selector("#app:not([hidden])")
    gravar_e_enviar(pagina_microfone)
    pagina_microfone.locator("#mensagens .msg.eu", has_text="🎤 calcular INSS").wait_for(timeout=15000)
    assert "salário" in ultima_resposta(pagina_microfone).lower()  # a resposta do chat (cálculo) volta pela voz
    assert not pagina_microfone.eval_on_selector("#botao-voz", "e => e.classList.contains('gravando')")
    (tamanho, nome, idioma), = stt.recebidos
    assert tamanho > 2000 and nome == "fala.webm" and idioma == "pt"  # áudio de verdade, em WebM, chegou ao servidor
    assert pagina_microfone.erros == []


def test_alternar_leitura_em_voz_alta_e_estado_do_botao_de_voz(pagina_microfone):
    entrar(pagina_microfone)
    pagina_microfone.wait_for_selector("#app:not([hidden])")
    assert pagina_microfone.get_attribute("#alternar-fala", "aria-pressed") == "false"
    pagina_microfone.click("#alternar-fala")
    assert pagina_microfone.get_attribute("#alternar-fala", "aria-pressed") == "true"
    assert pagina_microfone.get_attribute("#botao-voz", "aria-pressed") == "false"


def test_voz_sem_stt_configurado_avisa_na_tela_e_nao_grava(pagina_microfone):
    APP["app"].state.stt = None
    entrar(pagina_microfone)
    pagina_microfone.wait_for_selector("#app:not([hidden])")
    pagina_microfone.click("#botao-voz")
    pagina_microfone.wait_for_selector("#aviso:not([hidden])")
    assert "não está configurada" in pagina_microfone.inner_text("#aviso")
    assert not pagina_microfone.eval_on_selector("#botao-voz", "e => e.classList.contains('gravando')")


def test_microfone_com_o_whisper_de_verdade_a_fala_vira_texto_e_o_chat_responde(pagina_microfone):
    """Navegador -> WebSocket -> Whisper (API real) -> chat. Pulado sem GROQ_API_KEY."""
    from contabil_agente.tests.test_ia_ao_vivo import ENV
    from contabil_agente.voz import WhisperGroq

    if not ENV.get("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY não configurada (ponha em .env.teste para testar ao vivo)")
    APP["app"].state.stt = WhisperGroq(ENV["GROQ_API_KEY"])
    entrar(pagina_microfone)
    pagina_microfone.wait_for_selector("#app:not([hidden])")
    gravar_e_enviar(pagina_microfone)
    balao = pagina_microfone.locator("#mensagens .msg.eu", has_text="🎤").last
    balao.wait_for(timeout=20000)
    resposta = ultima_resposta(pagina_microfone)
    assert "rescis" in balao.inner_text().lower() and "rescis" in resposta.lower()  # a fala foi entendida e o chat conduziu o cálculo
