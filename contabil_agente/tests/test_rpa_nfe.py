"""Robô da consulta de NF-e com Playwright de verdade contra uma consulta falsa (formulário e hCaptcha com a estrutura da tela real)."""

import hashlib
import inspect
import json

import pytest

from contabil_agente.rpa import ConfigInvalida, ConfigPortalNFe, ErroDoRobo, HumanoNaoRespondeu, PortalBloqueouAutomacao, RoboConsultaNFe
from contabil_agente.rpa.robo_nfe import _decimal_br, _mascarar_cpfs, montar_resumo, pares_do_texto
from contabil_agente.security.worm_audit import WormAudit

from .portal_nfe_falso import NfeFalsa
from .test_rpa_fgts import canal  # noqa: F401 - fixture que escolhe o navegador disponível

CHAVE = "35260911222333000181550010000012341000001234"  # DV módulo 11 correto; número da nota 1234


@pytest.fixture()
def portal():
    p = NfeFalsa()
    yield p
    p.parar()


def config(portal, canal, **kw):
    kw = {"timeout_humano_s": 20, "timeout_navegacao_s": 20, "espera_resultado_s": 8, "espera_elemento_s": 5, **kw}
    return ConfigPortalNFe(url=portal.url, headless=True, canal=canal, **kw)


def humano_resolvendo(eventos):
    """Faz o papel da pessoa: quando o robô pausa no hCaptcha, resolve (o token de resposta é preenchido)."""
    def notificar(motivo, seletor, page):
        eventos.append((motivo, seletor))
        page.click("#humano-ok")

    return notificar


# ---------------------------------------------------------------- configuração
def test_config_padrao_traz_os_seletores_conferidos_ao_vivo_e_nao_herda_variaveis_de_outros_portais():
    c = ConfigPortalNFe.carregar(env={"FGTS_CAIXA_URL": "https://outro.gov.br", "NFE_BROWSER_CHANNEL": "msedge"})
    assert c.hosts[0] == "www.nfe.fazenda.gov.br" and c.canal == "msedge"
    assert c.seletores_cpf[0].endswith("txtChaveAcessoResumo") and c.seletores_envio[0].endswith("btnConsultarHCaptcha")
    with pytest.raises(ConfigInvalida):
        ConfigPortalNFe(url="http://www.nfe.fazenda.gov.br")  # HTTPS obrigatório fora do localhost
    with pytest.raises(ConfigInvalida):
        ConfigPortalNFe(padrao_resultado="(")
    with pytest.raises(ConfigInvalida):
        ConfigPortalNFe(tentativas_captcha=0)


def test_sem_extensao_de_captcha_nem_flag_de_evasao_no_codigo():
    import contabil_agente.rpa.config as c
    import contabil_agente.rpa.robo_nfe as r

    fonte = (inspect.getsource(r) + inspect.getsource(c)).lower()
    for proibido in ("buster", "load-extension", "automationcontrolled", "2captcha", "anticaptcha", "stealth", "excludeswitches"):
        assert proibido not in fonte


# ------------------------------------------------------- leitura da tela (sem navegador)
def test_decimal_br_e_mascara_de_cpf():
    assert _decimal_br("R$ 1.234,56") == "1234.56" and _decimal_br("987,65") == "987.65" and _decimal_br("sem numero") is None
    assert _mascarar_cpfs("CPF 529.982.247-25 e 52998224725 e CNPJ 11.222.333/0001-81") == "CPF ***.982.247-** e ***.982.247-** e CNPJ 11.222.333/0001-81"
    assert _mascarar_cpfs("12345678901") == "12345678901"  # 11 dígitos que não são CPF (DV errado) ficam como estão


def test_montar_resumo_separa_emitente_e_destinatario_e_nao_inventa_campo():
    pares = [
        {"secao": "Dados da NF-e", "rotulo": "Número", "valor": "77"},
        {"secao": "Dados da NF-e", "rotulo": "Valor Total da NF-e", "valor": "R$ 10,50"},
        {"secao": "Emitente", "rotulo": "CNPJ", "valor": "11.222.333/0001-81"},
        {"secao": "Emitente", "rotulo": "Nome/Razão Social", "valor": "ACME"},
        {"secao": "Destinatário", "rotulo": "UF", "valor": "RJ"},
        {"secao": "Situação Atual", "rotulo": "Situação", "valor": "AUTORIZADA"},
        {"secao": "Transporte", "rotulo": "Placa", "valor": "ABC1D23"},
    ]
    r = montar_resumo(pares)
    assert r["numero"] == "77" and r["valor_total_decimal"] == "10.50" and r["situacao"] == "AUTORIZADA"
    assert r["emitente"] == {"documento": "11.222.333/0001-81", "nome": "ACME"} and r["destinatario"] == {"uf": "RJ"}
    assert "placa" not in json.dumps(r).lower() and "serie" not in r  # o que a tela não trouxe não aparece


def test_pares_do_texto_le_rotulo_dois_pontos_valor():
    assert pares_do_texto("Resultado\nNúmero: 12\nSituação: AUTORIZADA\nlinha solta") == [
        {"secao": "", "rotulo": "Número", "valor": "12"}, {"secao": "", "rotulo": "Situação", "valor": "AUTORIZADA"}]


# ------------------------------------------------------------------ robô de ponta a ponta
def test_fluxo_completo_o_robo_espera_o_humano_resolver_o_hcaptcha_e_le_a_nota(portal, canal, tmp_path):
    eventos = []
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    robo = RoboConsultaNFe(config(portal, canal), tmp_path / "w", audit, tenant="t1", notificar_humano=humano_resolvendo(eventos), chave_hash="h" * 20)
    r = robo.executar(" ".join(CHAVE[i:i + 4] for i in range(0, 44, 4)))  # aceita a chave como aparece nos documentos, com espaços

    assert eventos and "hCaptcha" in eventos[0][0]  # o robô pausou e chamou a pessoa
    envio = portal.envios[0]
    assert envio["ctl00$ContentPlaceHolder1$txtChaveAcessoResumo"] == CHAVE
    assert envio["h-captcha-response"].startswith("token-do-captcha")  # só enviou depois de a pessoa resolver

    arquivo = open(r.caminho, "rb").read()
    assert hashlib.sha256(arquivo).hexdigest() == r.sha256 and r.tamanho == len(arquivo)
    resumo = r.dados["resumo"]
    assert resumo["numero"] == "1234" and resumo["serie"] == "1" and resumo["modelo"] == "55" and resumo["data_emissao"] == "15/09/2026"
    assert resumo["valor_total_decimal"] == "1234.56" and resumo["situacao"] == "AUTORIZADA" and resumo["protocolo"] == "135260000012345"
    assert resumo["emitente"] == {"documento": "11.222.333/0001-81", "nome": "COMERCIO DE TESTE LTDA", "uf": "SP"}
    assert resumo["destinatario"]["documento"] == "***.982.247-**" and resumo["destinatario"]["nome"] == "FULANO DE TAL"
    assert "529.982.247-25" not in arquivo.decode() and r.dados["chave"] == CHAVE
    nomes = [p["passo"] for p in r.passos]
    assert nomes[0] == "inicio" and "humano_resolveu" in nomes and "resultado_na_tela" in nomes and nomes[-1] == "fim"
    assert r.to_dict()["dados"]["resumo"]["numero"] == "1234"


@pytest.mark.parametrize("estrutura,numero,situacao", [("tabela", "1234", "CANCELADA"), ("linhas", "1234", "AUTORIZADA")])
def test_le_a_nota_em_outras_estruturas_de_html(canal, tmp_path, estrutura, numero, situacao):
    p = NfeFalsa(estrutura=estrutura)
    try:
        r = RoboConsultaNFe(config(p, canal), tmp_path, notificar_humano=humano_resolvendo([])).executar(CHAVE)
        assert r.dados["resumo"]["numero"] == numero and r.dados["resumo"]["situacao"] == situacao
    finally:
        p.parar()


def test_tela_da_nota_sem_rotulos_falha_dizendo_o_que_aconteceu_e_salva_o_diagnostico(canal, tmp_path):
    p = NfeFalsa(estrutura="sem_rotulos")
    try:
        with pytest.raises(ErroDoRobo) as e:
            RoboConsultaNFe(config(p, canal), tmp_path, notificar_humano=humano_resolvendo([])).executar(CHAVE)
        assert e.value.motivo == "resumo_nao_interpretado"
        assert list(tmp_path.glob("diagnostico_resumo_nfe_*.json"))  # estrutura mascarada para ajustar a configuração
    finally:
        p.parar()


def test_nota_inexistente_diz_isso_sem_repetir_a_consulta(canal, tmp_path):
    p = NfeFalsa(notas_existentes=("0" * 44,))
    try:
        with pytest.raises(ErroDoRobo) as e:
            RoboConsultaNFe(config(p, canal), tmp_path, notificar_humano=humano_resolvendo([])).executar(CHAVE)
        assert e.value.motivo == "nota_nao_encontrada"
    finally:
        p.parar()


def test_captcha_vencido_a_pessoa_resolve_de_novo(canal, tmp_path):
    p = NfeFalsa(rejeitar_primeiro_token=True)
    eventos = []
    try:
        r = RoboConsultaNFe(config(p, canal), tmp_path, notificar_humano=humano_resolvendo(eventos)).executar(CHAVE)
        assert len(p.envios) == 2 and len(eventos) == 2  # o portal devolveu o formulário; o robô pediu a pessoa outra vez
        assert r.dados["resumo"]["numero"] == "1234" and "consulta_nao_concluida" in [x["passo"] for x in r.passos]
    finally:
        p.parar()


def test_ninguem_resolve_o_captcha_o_robo_para_e_nao_envia_nada(portal, canal, tmp_path):
    cfg = config(portal, canal, timeout_humano_s=3)
    with pytest.raises(HumanoNaoRespondeu):
        RoboConsultaNFe(cfg, tmp_path, notificar_humano=lambda m, s, page: None).executar(CHAVE)
    assert portal.envios == []  # sem a pessoa, o formulário nem foi enviado


def test_chave_invalida_nem_abre_o_navegador(portal, canal, tmp_path):
    robo = RoboConsultaNFe(config(portal, canal), tmp_path)
    for ruim in ("123", CHAVE[:-1] + "0", "x" * 44):
        with pytest.raises(ErroDoRobo) as e:
            robo.executar(ruim)
        assert e.value.motivo == "chave_invalida"
    assert portal.envios == []


def test_portal_que_reprova_o_navegador_automatizado_para_sem_nova_tentativa(canal, tmp_path):
    p = NfeFalsa(bloquear=True)
    try:
        with pytest.raises(PortalBloqueouAutomacao):
            RoboConsultaNFe(config(p, canal), tmp_path, notificar_humano=humano_resolvendo([])).executar(CHAVE)
        assert len(p.envios) == 1  # insistir só pioraria
    finally:
        p.parar()


def test_trilha_usa_prefixo_nfe_e_nao_guarda_a_chave(portal, canal, tmp_path):
    audit = WormAudit(tmp_path / "audit", "k" * 40, fsync=False)
    RoboConsultaNFe(config(portal, canal), tmp_path / "w", audit, tenant="t1", notificar_humano=humano_resolvendo([]), chave_hash="h" * 20).executar(CHAVE)
    bruto = (tmp_path / "audit" / "t1.worm.jsonl").read_text(encoding="utf-8")
    assert "rpa.nfe.resumo_salvo" in bruto and "rpa.fgts" not in bruto
    assert CHAVE not in bruto and audit.verificar("t1").ok


# ------------------------------------------------------------------ CT-e e NFC-e
from contabil_agente.rpa import ConfigPortalCTe, ConfigPortalNFCe, config_para_chave  # noqa: E402

from .portal_nfe_falso import CODIGO_DA_IMAGEM, chave_com_dv  # noqa: E402

CHAVE_CTE = chave_com_dv("3526091122233300018157001000004321100000123")  # modelo 57, número 4321
CHAVE_NFCE_SP = chave_com_dv("3526091122233300018165001000000777100000999")  # modelo 65, UF 35, número 777
CHAVE_NFCE_RJ = chave_com_dv("3326091122233300018165001000000777100000999")
CHAVE_MDFE = chave_com_dv("3526091122233300018158001000000001100000001")  # modelo 58 (MDF-e): não atendido


def test_cada_chave_vai_para_o_portal_do_seu_modelo():
    nfe, cte, nfce = ConfigPortalNFe(), ConfigPortalCTe(), ConfigPortalNFCe()
    assert config_para_chave(CHAVE, nfe, cte, nfce) is nfe
    assert config_para_chave(CHAVE_CTE, nfe, cte, nfce) is cte and cte.hosts[0] == "www.cte.fazenda.gov.br"
    assert config_para_chave(CHAVE_NFCE_SP, nfe, cte, nfce) is nfce and nfce.hosts[0] == "www.nfce.fazenda.sp.gov.br"
    assert cte.seletores_cpf == nfe.seletores_cpf and nfce.seletores_captcha_imagem == ("#txCodigo",)  # conferidos ao vivo
    for chave, motivo in ((CHAVE_NFCE_RJ, "nfce_de_outra_uf"), (CHAVE_MDFE, "modelo_nao_suportado"), ("123", "chave_invalida")):
        with pytest.raises(ErroDoRobo) as e:
            config_para_chave(chave, nfe, cte, nfce)
        assert e.value.motivo == motivo
    assert config_para_chave(CHAVE_NFCE_RJ, nfe, cte, ConfigPortalNFCe(url="https://consultadfe.fazenda.rj.gov.br/x", uf="33")).uf == "33"


def test_robo_da_nfe_recusa_chave_de_ct_e_sem_abrir_o_navegador(portal, canal, tmp_path):
    with pytest.raises(ErroDoRobo) as e:
        RoboConsultaNFe(config(portal, canal), tmp_path).executar(CHAVE_CTE)
    assert e.value.motivo == "modelo_errado" and "CT-e" in str(e.value) and portal.envios == []


def test_ct_e_de_ponta_a_ponta(canal, tmp_path):
    p = NfeFalsa(estrutura="cte")
    try:
        cfg = ConfigPortalCTe(url=p.url, headless=True, canal=canal, timeout_humano_s=20, timeout_navegacao_s=20, espera_resultado_s=8)
        r = RoboConsultaNFe(cfg, tmp_path, notificar_humano=humano_resolvendo([])).executar(CHAVE_CTE)
    finally:
        p.parar()
    resumo = r.dados["resumo"]
    assert resumo["numero"] == "4321" and resumo["valor_total_decimal"] == "350.00" and resumo["situacao"] == "AUTORIZADO"
    assert resumo["tomador"] == {"documento": "11.222.333/0001-81"} and resumo["emitente"]["nome"] == "TRANSPORTES TESTE LTDA"
    assert r.dados["modelo"] == "CT-e" and "consulta_cte_" in r.caminho


def test_nfc_e_de_sp_a_pessoa_digita_o_codigo_da_imagem_e_erra_na_primeira(canal, tmp_path):
    p = NfeFalsa(nfce_sp=True)
    codigos, avisos = iter(["ERRADO", CODIGO_DA_IMAGEM]), []

    def pessoa(motivo, seletor, page):
        avisos.append(motivo)
        if seletor == "assistencia":  # o aviso amarelo apareceu na janela: lê a imagem, digita e clica em "Terminei"
            page.fill("#txCodigo", next(codigos))
            page.evaluate("() => { window.__roboTerminei = true; }")  # o mesmo efeito do botão "Terminei esta etapa"

    try:
        cfg = ConfigPortalNFCe(url=p.url, headless=True, canal=canal, timeout_humano_s=20, timeout_navegacao_s=20, espera_resultado_s=6)
        r = RoboConsultaNFe(cfg, tmp_path, notificar_humano=pessoa).executar(CHAVE_NFCE_SP)
    finally:
        p.parar()
    assert len(p.envios) == 2 and p.envios[1]["txCodigo"] == CODIGO_DA_IMAGEM and len(avisos) == 2
    assert r.dados["resumo"]["numero"] == "777" and r.dados["resumo"]["situacao"] == "AUTORIZADA" and r.dados["modelo"] == "NFC-e"
    assert "humano_digitou_o_codigo" in [x["passo"] for x in r.passos]
