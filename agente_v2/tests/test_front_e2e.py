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
