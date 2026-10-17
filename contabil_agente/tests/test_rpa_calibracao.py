"""O gravador de calibragem contra o portal falso: grava a estrutura e nunca o que a pessoa digita."""

import hashlib
import json
import os

from contabil_agente.rpa.calibracao import calibrar

from .portal_fgts_falso import PortalFalso
from .test_rpa_fgts import canal  # noqa: F401 - fixture que escolhe o navegador disponível

CPF = "529.982.247-25"


def _pessoa(contexto, esperar):
    """Faz o papel da pessoa: digita o CPF, consulta e clica no extrato (que baixa um PDF), com pausas de quem lê a tela."""
    pagina = contexto.pages[0]
    esperar(2)
    pagina.click("#cpf")  # a pessoa clica no campo antes de digitar
    pagina.keyboard.type(CPF)
    pagina.click("button:has-text('Consultar')")
    pagina.wait_for_selector("a:has-text('Extrato')")
    esperar(2)
    with pagina.expect_download():
        pagina.click("a:has-text('Extrato')")


def test_grava_navegacao_cliques_seletores_e_download_sem_gravar_o_que_foi_digitado(canal, tmp_path):
    portal = PortalFalso(com_captcha=False)
    try:
        rel = calibrar(portal.url, tmp_path / "cal", canal=canal, headless=True, humano=_pessoa)
    finally:
        portal.parar()

    assert rel["hosts"] == ["127.0.0.1"]
    cliques = [e for e in rel["eventos"] if e["evento"] == "clique"]
    sugestoes = [s for c in cliques for s in c["sugestoes"]]
    assert "#cpf" in sugestoes and "button:has-text('Consultar')" in sugestoes and "a:has-text('Extrato')" in sugestoes
    navegacoes = [e for e in rel["eventos"] if e["evento"] == "navegou"]
    assert {n["caminho"] for n in navegacoes} >= {"/", "/consulta"}

    # a estrutura da página também é gravada (campos e botões visíveis)
    instantaneos = [e for e in rel["eventos"] if e["evento"] == "elementos"]
    assert any(any(el["id"] == "cpf" for el in i["elementos"]) for i in instantaneos)

    # o PDF baixado é conferido (assinatura, tamanho, SHA-256) e guardado
    (baixado,) = rel["downloads"]
    assert baixado["e_pdf"] and baixado["sha256"] == hashlib.sha256(portal.pdf).hexdigest()
    assert os.path.isfile(baixado["arquivo_local"])
    if os.name != "nt":
        assert (os.stat(baixado["arquivo_local"]).st_mode & 0o777) == 0o600

    # o que a pessoa digitou NÃO está em lugar nenhum do relatório
    texto = (tmp_path / "cal" / "calibragem.json").read_text(encoding="utf-8")
    assert CPF not in texto and "52998224725" not in texto and json.loads(texto)["cliques"] >= 3


def test_numeros_longos_e_emails_sao_mascarados_nos_textos(canal, tmp_path):
    portal = PortalFalso(com_captcha=False)

    def pessoa(contexto, esperar):
        pagina = contexto.pages[0]
        pagina.evaluate("document.body.insertAdjacentHTML('beforeend', '<button id=\"b\">Conta 123456789 joao@x.com</button>')")
        pagina.click("#b")

    try:
        rel = calibrar(portal.url, tmp_path / "cal", canal=canal, headless=True, humano=pessoa)
    finally:
        portal.parar()
    texto = json.dumps(rel, ensure_ascii=False)
    assert "123456789" not in texto and "joao@x.com" not in texto and "####" in texto and "***@***" in texto
