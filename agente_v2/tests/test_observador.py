"""Pasta observada: o PDF baixado no navegador normal entra sozinho no pipeline, pela API de verdade (sem robô no portal)."""

import json
import os
import time

import pytest

from agente_v2 import cli
from agente_v2.observador import ARQUIVO_ESTADO, ClienteAPI, ErroDeEnvio, ObservadorDePasta
from contabil_agente.tests.portal_fgts_falso import pdf_extrato
from contabil_agente.tests.portal_pgmei_falso import pdf_pgmei

from .test_api import SENHA, client, llm  # noqa: F401


def _novo(pasta, nome, dados, idade_s=0.0):
    p = pasta / nome
    p.write_bytes(dados)
    if idade_s:
        antes = time.time() - idade_s
        os.utime(p, (antes, antes))
    return p


def _duas_voltas(obs):
    """A 1ª volta vê o arquivo; a 2ª confirma que ele parou de crescer e o envia."""
    assert obs.varrer() == []
    return obs.varrer()


# ------------------------------------------------------------------ regras do observador (sem API)
def test_so_envia_depois_que_o_arquivo_para_de_crescer(tmp_path):
    enviados = []
    obs = ObservadorDePasta(tmp_path, lambda p: (enviados.append(p.name), {"tipo": "DAS", "estado": "ARCHIVED"})[1], desde=0)
    arq = _novo(tmp_path, "das.pdf", b"%PDF-1.4 parte")
    assert obs.varrer() == []
    arq.write_bytes(b"%PDF-1.4 parte e mais um pedaco")  # o navegador ainda está gravando
    assert obs.varrer() == [] and enviados == []
    r = obs.varrer()
    assert [x["status"] for x in r] == ["enviado"] and enviados == ["das.pdf"] and r[0]["tipo"] == "DAS"
    assert obs.varrer() == []  # não manda de novo


def test_ignora_o_que_nao_e_pdf_o_que_ja_estava_na_pasta_e_download_incompleto(tmp_path):
    _novo(tmp_path, "antigo.pdf", b"%PDF-1.4 velho", idade_s=3600)  # já estava na pasta antes de começar
    enviados = []
    obs = ObservadorDePasta(tmp_path, lambda p: enviados.append(p) or {})  # desde = agora
    _novo(tmp_path, "baixando.pdf.crdownload", b"%PDF-1.4 meio")
    _novo(tmp_path, "falso.pdf", b"<html>nao e pdf</html>")
    r = _duas_voltas(obs)
    assert r == [{"arquivo": "falso.pdf", "status": "ignorado", "motivo": "não é PDF"}] and enviados == []


def test_mesmo_conteudo_com_outro_nome_nao_e_enviado_de_novo_nem_depois_de_reiniciar(tmp_path):
    enviados = []
    enviar = lambda p: enviados.append(p.name) or {"tipo": "FGTS_EXTRATO"}  # noqa: E731
    pdf = pdf_extrato()
    _novo(tmp_path, "extrato.pdf", pdf)
    assert [x["status"] for x in _duas_voltas(ObservadorDePasta(tmp_path, enviar, desde=0))] == ["enviado"]
    assert json.loads((tmp_path / ARQUIVO_ESTADO).read_text(encoding="utf-8"))  # o SHA-256 fica guardado
    _novo(tmp_path, "extrato (1).pdf", pdf)  # o navegador baixou o mesmo arquivo de novo
    r = _duas_voltas(ObservadorDePasta(tmp_path, enviar, desde=0))  # outro processo: lê o estado da pasta
    assert {x["status"] for x in r} == {"ignorado"} and enviados == ["extrato.pdf"]


def test_falha_temporaria_tenta_de_novo_e_recusa_definitiva_nao(tmp_path):
    respostas = [ErroDeEnvio("API inacessível", definitivo=False), {"tipo": "DAS", "estado": "ARCHIVED"}]

    def enviar(p):
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    _novo(tmp_path, "das.pdf", b"%PDF-1.4 x")
    obs = ObservadorDePasta(tmp_path, enviar, desde=0)
    assert [x["status"] for x in _duas_voltas(obs)] == ["tentar_de_novo"]
    assert [x["status"] for x in _duas_voltas(obs)] == ["enviado"]

    def recusar(p):
        raise ErroDeEnvio("422 arquivo ilegível", definitivo=True)

    _novo(tmp_path, "ruim.pdf", b"%PDF-1.4 y")
    obs2 = ObservadorDePasta(tmp_path, recusar, desde=0)
    r = _duas_voltas(obs2)
    assert [x["status"] for x in r if x["arquivo"] == "ruim.pdf"] == ["recusado"] and obs2.varrer() == []


def test_pasta_que_nao_existe_da_erro_claro(tmp_path):
    with pytest.raises(ValueError):
        ObservadorDePasta(tmp_path / "nao_existe", lambda p: {})


# ------------------------------------------------------------------ de ponta a ponta, pela API
def test_extrato_e_das_baixados_no_navegador_entram_no_pipeline_pela_api(client, tmp_path):
    pasta = tmp_path / "Downloads"
    pasta.mkdir()
    obs = ObservadorDePasta(pasta, ClienteAPI("", "maria", SENHA, cliente=client), desde=0)
    _novo(pasta, "extrato_fgts.pdf", pdf_extrato())
    _novo(pasta, "DAS-PGMEI.pdf", pdf_pgmei())
    r = {x["arquivo"]: x for x in _duas_voltas(obs)}
    assert r["extrato_fgts.pdf"]["status"] == "enviado" and r["extrato_fgts.pdf"]["tipo"] == "FGTS_EXTRATO"
    assert r["DAS-PGMEI.pdf"]["status"] == "enviado" and r["DAS-PGMEI.pdf"]["tipo"] == "DAS"
    assert r["DAS-PGMEI.pdf"]["estado"] == "ARCHIVED"


def test_senha_errada_e_recusa_definitiva(client, tmp_path):
    with pytest.raises(ErroDeEnvio) as e:
        ClienteAPI("", "maria", "senha-errada", cliente=client)(_novo(tmp_path, "a.pdf", pdf_pgmei()))
    assert e.value.definitivo is True


def test_cli_observar_pasta_uma_vez(client, tmp_path, monkeypatch, capsys):
    import agente_v2.observador as mod

    monkeypatch.setattr(mod.httpx, "Client", lambda **kw: client)  # a CLI fala com a API real em memória
    monkeypatch.setenv("AGENTE_SENHA", SENHA)
    _novo(tmp_path, "DAS.pdf", pdf_pgmei())
    codigo = cli.main(["observar-pasta", "--pasta", str(tmp_path), "--api", "", "--usuario", "maria", "--intervalo", "0.05",
                       "--incluir-existentes", "--uma-vez"])
    linhas = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    assert codigo == 0 and linhas[0]["status"] == "enviado" and linhas[0]["tipo"] == "DAS"


def test_xml_da_nfe_baixado_pelo_web_service_entra_pela_api_como_nfe_xml(client, tmp_path):
    from contabil_agente.tests.sefaz_falsa import proc_nfe

    chave = "35260911222333000181550010000012341000001234"
    xml = _novo(tmp_path, f"nfe_{chave}.xml", proc_nfe(chave))
    doc = ClienteAPI("", "maria", SENHA, cliente=client)(xml)
    assert doc["tipo"] == "NFE_XML" and doc["estado"] == "ARCHIVED"
