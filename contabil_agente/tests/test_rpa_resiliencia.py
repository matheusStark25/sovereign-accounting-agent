"""O robô não pode travar por bobeira: site que muda de layout, que demora, que usa iframe ou que o robô não entende.

Cada caso usa o portal falso com a variante correspondente. A pessoa (o "humano" dos testes) só entra quando o robô
pede; em tudo que dá para resolver sozinho, ela não é chamada.
"""

import json

import pytest

from contabil_agente.rpa import ConfigInvalida, ConfigPortalFGTS, ErroDoRobo, HumanoNaoRespondeu, PortaDoHumano, PortalBloqueouAutomacao, RoboExtratoFGTS
from contabil_agente.rpa.humano import _JS_AJUDA

from .portal_fgts_falso import PortalFalso
from .test_rpa_fgts import CPF, canal  # noqa: F401 - fixture que escolhe o navegador disponível


def config(portal, canal, **kw):
    kw.setdefault("espera_elemento_s", 3)
    return ConfigPortalFGTS(url=portal.url, headless=True, canal=canal, timeout_humano_s=20, timeout_navegacao_s=20, timeout_download_s=10, **kw)


def _com_portal(variante, **kw):
    p = PortalFalso(com_captcha=False, variante=variante, **kw)
    return p


def _passos(r, nome):
    return [x for x in r.passos if x["passo"] == nome]


def test_site_com_layout_novo_o_robo_se_vira_sozinho_e_diz_o_que_atualizar(canal, tmp_path):
    p = _com_portal("layout_novo")
    chamadas = []
    try:
        cfg = config(p, canal, seletores_cpf=("#cpf",), seletores_envio=("#enviar",))  # os do site antigo, que não valem mais
        r = RoboExtratoFGTS(cfg, tmp_path, notificar_humano=lambda *a: chamadas.append(a)).executar(CPF)
    finally:
        p.parar()
    assert chamadas == []  # a pessoa não foi incomodada
    por_etapa = {x["etapa"]: x for x in _passos(r, "seletor_alternativo")}
    assert por_etapa["cpf"]["sugestao"] == "#campo-documento"  # sugere o seletor para pôr na configuração
    assert por_etapa["envio"]["achou_por"] == "botão pelo texto"
    assert por_etapa["download"]["achou_por"] == "download pelo texto (link)"
    assert open(r.caminho, "rb").read().startswith(b"%PDF-")


def test_pagina_que_monta_a_tela_depois_e_esperada_e_nao_derrubada(canal, tmp_path):
    p = _com_portal("tardia")
    try:
        r = RoboExtratoFGTS(config(p, canal, espera_elemento_s=10), tmp_path).executar(CPF)
        assert any("52998224725" in c for c in p.cpfs_recebidos) and r.tamanho > 100
    finally:
        p.parar()


def test_sem_esperar_o_mesmo_site_falharia_por_isso_a_espera_importa(canal, tmp_path):
    p = _com_portal("tardia")
    try:
        with pytest.raises(ErroDoRobo) as e:
            RoboExtratoFGTS(config(p, canal, espera_elemento_s=1, ajuda_humana=False), tmp_path).executar(CPF)
        assert e.value.motivo == "campo_cpf_nao_encontrado"
    finally:
        p.parar()


def test_formulario_dentro_de_iframe_e_encontrado(canal, tmp_path):
    p = _com_portal("iframe")
    try:
        r = RoboExtratoFGTS(config(p, canal), tmp_path).executar(CPF)
        assert any("52998224725" in c for c in p.cpfs_recebidos) and open(r.caminho, "rb").read().startswith(b"%PDF-")
    finally:
        p.parar()


def test_link_do_pdf_irreconhecivel_a_pessoa_clica_e_o_robo_pega_o_arquivo(canal, tmp_path):
    p = _com_portal("link_sem_pistas")
    pedidos = []

    def pessoa(motivo, seletor, page):
        pedidos.append((motivo, seletor))
        page.click("a#x")  # a pessoa clica no link; o download é dela

    try:
        r = RoboExtratoFGTS(config(p, canal), tmp_path, notificar_humano=pessoa).executar(CPF)
    finally:
        p.parar()
    assert pedidos and pedidos[0][1] == "assistencia" and pedidos[0][0].startswith("download")
    assert open(r.caminho, "rb").read().startswith(b"%PDF-")
    nomes = [x["passo"] for x in r.passos]
    assert "humano_fez_a_etapa" in nomes and "diagnostico_salvo" in nomes and nomes[-1] == "fim"
    # o diagnóstico mostra o que existia na página (para ajustar a configuração) e nunca o CPF
    (arq,) = list(tmp_path.glob("diagnostico_download_*.json"))
    texto = arq.read_text(encoding="utf-8")
    assert "Clique aqui" in texto and "52998224725" not in texto and CPF not in texto
    assert json.loads(texto)["etapa"] == "download"


def test_campo_do_cpf_nao_identificavel_a_pessoa_preenche_e_o_robo_continua(canal, tmp_path):
    p = _com_portal("campo_desconhecido")

    def pessoa(motivo, seletor, page):
        page.fill("input[name=x1]", CPF)
        page.evaluate("() => { window.__roboTerminei = true; }")  # o mesmo efeito do botão "Terminei esta etapa"

    try:
        r = RoboExtratoFGTS(config(p, canal), tmp_path, notificar_humano=pessoa).executar(CPF)
    finally:
        p.parar()
    assert any("52998224725" in c.replace(".", "").replace("-", "") for c in p.cpfs_recebidos)  # o que a pessoa digitou chegou ao portal
    nomes = [x["passo"] for x in r.passos]
    assert nomes.index("humano_fez_a_etapa") < nomes.index("envio_clicado") and r.segundos_com_humano > 0
    assert CPF not in json.dumps(r.passos)  # nada de CPF nos passos


def test_portal_que_bloqueia_o_robo_falha_claro_e_sem_nova_tentativa(canal, tmp_path):
    p = _com_portal("bloqueado")
    pedidos = []
    try:
        robo = RoboExtratoFGTS(config(p, canal), tmp_path, notificar_humano=lambda *a: pedidos.append(a))
        with pytest.raises(PortalBloqueouAutomacao) as e:
            robo.executar(CPF)
    finally:
        p.parar()
    assert e.value.motivo == "portal_bloqueou_automacao" and "navegador normal" in str(e.value)
    assert p.visitas_raiz == 1  # não insistiu: tentar de novo só piora
    assert pedidos == []  # e não pediu ajuda à pessoa, que não adiantaria
    assert any(x["passo"] == "portal_bloqueou_automacao" for x in robo._passos)


def test_aviso_na_janela_tem_o_botao_terminei_e_o_robo_segue_quando_a_pessoa_clica(canal, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel=canal, headless=True)
        try:
            page = b.new_page()
            page.set_content("<html><body><p>qualquer portal</p></body></html>")
            porta = PortaDoHumano((), timeout_s=10, intervalo_s=0.2)
            vezes = []

            def pessoa_clica():
                if page.locator("#__robo_terminei").count():
                    vezes.append(page.locator("#__robo_ajuda_texto").inner_text())
                    page.click("#__robo_terminei")
                return False

            espera = porta.assistir(page, "campo_cpf", "Preencha o campo e clique no botão.", concluido=pessoa_clica)
            assert vezes == ["Preencha o campo e clique no botão."] and espera >= 0
            assert page.locator("#__robo_ajuda").count() == 0  # o aviso some depois
        finally:
            b.close()


def test_se_ninguem_faz_a_etapa_o_robo_para_com_erro_claro(canal, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel=canal, headless=True)
        try:
            page = b.new_page()
            page.set_content("<html><body></body></html>")
            with pytest.raises(HumanoNaoRespondeu):
                PortaDoHumano((), timeout_s=2, intervalo_s=0.2).assistir(page, "download", "Clique no PDF.")
        finally:
            b.close()


def test_config_recusa_regex_invalida_e_espera_nao_positiva():
    with pytest.raises(ConfigInvalida):
        ConfigPortalFGTS(rotulo_campo="(")
    with pytest.raises(ConfigInvalida):
        ConfigPortalFGTS(espera_elemento_s=0)


def test_js_do_aviso_nao_depende_de_nada_alem_do_texto():
    assert "__robo_terminei" in _JS_AJUDA and "window.__roboTerminei" in _JS_AJUDA
