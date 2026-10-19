"""XML completo da NF-e pelo NFeDistribuicaoDFe: mTLS de verdade com um .pfx, o envelope SOAP certo e cada resposta da SEFAZ tratada."""

import base64
import gzip
import os

import pytest

from contabil_agente.documentos.processador import processar_documento
from contabil_agente.sefaz import URLS, CertificadoA1, ClienteDistribuicao, ErroDistribuicao, ler_resposta, montar_pedido
from contabil_agente.sefaz.distribuicao import LIMITE_XML

from .sefaz_falsa import CNPJ_EMPRESA, SENHA_PFX, IcpDeTeste, SefazFalsa, resposta

CHAVE = "35260911222333000181550010000012341000001234"


@pytest.fixture(scope="module")
def icp(tmp_path_factory):
    return IcpDeTeste(tmp_path_factory.mktemp("icp"))


def cliente(icp, sefaz, **kw):
    return ClienteDistribuicao(CertificadoA1(icp.pfx, SENHA_PFX), "SP", url=sefaz.url, verificar=str(icp.ca_pem), **kw)


# ------------------------------------------------------------------ certificado
def test_le_o_pfx_e_acha_o_cnpj_no_campo_da_icp_brasil_ou_no_nome(icp, tmp_path):
    cert = CertificadoA1(icp.pfx, SENHA_PFX)
    assert cert.cnpj == CNPJ_EMPRESA
    so_nome = tmp_path / "so_nome.pfx"
    so_nome.write_bytes(icp.emitir_pfx(f"OUTRA EMPRESA:{CNPJ_EMPRESA}", cnpj_no_san=False))
    assert CertificadoA1(so_nome, SENHA_PFX).cnpj == CNPJ_EMPRESA
    with pytest.raises(ErroDistribuicao) as e:
        CertificadoA1(icp.pfx, "senha errada")
    assert e.value.motivo == "certificado_invalido"


def test_certificado_vencido_e_recusado_antes_de_ir_a_sefaz(tmp_path):
    with pytest.raises(ErroDistribuicao) as e:
        CertificadoA1(IcpDeTeste(tmp_path, vencido=True).pfx, SENHA_PFX)
    assert e.value.motivo == "certificado_vencido"


def test_a_chave_privada_nao_fica_no_disco_nem_em_claro(icp):
    cert = CertificadoA1(icp.pfx, SENHA_PFX)
    import tempfile

    with cert.contexto_tls():
        pastas = [p for p in os.listdir(tempfile.gettempdir()) if p.startswith("cert_a1_")]
        assert pastas
        conteudo = open(os.path.join(tempfile.gettempdir(), pastas[-1], "chave.pem"), "rb").read()
        assert b"ENCRYPTED PRIVATE KEY" in conteudo  # cifrada com senha aleatória
    assert not [p for p in os.listdir(tempfile.gettempdir()) if p.startswith("cert_a1_") and p in pastas]  # apagada no fim


# ------------------------------------------------------------------ pedido e resposta
def test_envelope_soap_no_formato_do_distdfeint():
    xml = montar_pedido("11.222.333/0001-81", "35", "producao", CHAVE).decode()
    assert '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">' in xml
    assert f"<tpAmb>1</tpAmb><cUFAutor>35</cUFAutor><CNPJ>{CNPJ_EMPRESA}</CNPJ><consChNFe><chNFe>{CHAVE}</chNFe></consChNFe>" in xml
    assert "<tpAmb>2</tpAmb>" in montar_pedido(CNPJ_EMPRESA, "35", "homologacao", CHAVE).decode()
    assert "<CPF>52998224725</CPF>" in montar_pedido("529.982.247-25", "35", "producao", CHAVE).decode()
    assert URLS["producao"].startswith("https://www1.nfe.fazenda.gov.br/") and URLS["homologacao"].startswith("https://hom1.nfe.fazenda.gov.br/")


def test_resposta_com_xml_perigoso_ou_bomba_de_compactacao_e_recusada():
    with pytest.raises(ErroDistribuicao):
        ler_resposta(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><x>&b;</x>')
    bomba = base64.b64encode(gzip.compress(b"0" * (LIMITE_XML + 10))).decode()
    corpo = resposta("138", "ok").replace(b"</retDistDFeInt>", f'<loteDistDFeInt><docZip NSU="1" schema="procNFe_v4.00.xsd">{bomba}</docZip></loteDistDFeInt></retDistDFeInt>'.encode())
    with pytest.raises(ErroDistribuicao) as e:
        ler_resposta(corpo)
    assert e.value.motivo == "documento_grande_demais"


# ------------------------------------------------------------------ de ponta a ponta, com mTLS
def test_baixa_o_xml_com_mtls_e_o_xml_entra_no_pipeline(icp, tmp_path):
    sefaz = SefazFalsa(icp)
    try:
        xml, resp = cliente(icp, sefaz).baixar_xml(CHAVE, tmp_path)
    finally:
        sefaz.parar()
    pedido = sefaz.pedidos[0]
    assert pedido["certificado"] == f"EMPRESA TESTE LTDA:{CNPJ_EMPRESA}"  # a SEFAZ viu o certificado da empresa na conexão
    assert 'action="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"' in pedido["tipo"]
    assert f"<chNFe>{CHAVE}</chNFe>" in pedido["corpo"] and resp.cstat == "138"
    assert xml.caminho.endswith(f"nfe_{CHAVE}.xml") and xml.chave == CHAVE
    doc = processar_documento(xml.caminho)
    assert doc.tipo == "NFE_XML" and doc.extracted_data["chave_acesso"] == CHAVE and doc.extracted_data["valor_nota"] == "1234.56"
    assert not [a for a in doc.alertas if a.severidade == "erro"]


@pytest.mark.parametrize("modo,motivo", [("resumo", "so_resumo"), ("nenhum", "cstat_137"), ("consumo_indevido", "cstat_656"),
                                         ("outra_nota", "xml_de_outra_nota")])
def test_cada_resposta_sem_xml_diz_o_motivo_e_nao_grava_nada(icp, tmp_path, modo, motivo):
    sefaz = SefazFalsa(icp, modo)
    try:
        with pytest.raises(ErroDistribuicao) as e:
            cliente(icp, sefaz).baixar_xml(CHAVE, tmp_path)
    finally:
        sefaz.parar()
    assert e.value.motivo == motivo and not list(tmp_path.glob("*.xml"))
    if modo == "resumo":
        assert "Ciência da Operação" in str(e.value)
    if modo == "consumo_indevido":
        assert "1 hora" in str(e.value)


def test_certificado_de_outra_cadeia_nao_conecta(icp, tmp_path):
    estranho = IcpDeTeste(tmp_path / "outra")  # outra CA: a SEFAZ (falsa) não confia nele
    sefaz = SefazFalsa(icp)
    try:
        c = ClienteDistribuicao(CertificadoA1(estranho.pfx, SENHA_PFX), "SP", url=sefaz.url, verificar=str(icp.ca_pem))
        with pytest.raises(ErroDistribuicao) as e:
            c.consultar_chave(CHAVE)
    finally:
        sefaz.parar()
    assert e.value.motivo == "sefaz_inacessivel" and sefaz.pedidos == []


def test_validacoes_antes_de_chamar_a_sefaz(icp):
    cert = CertificadoA1(icp.pfx, SENHA_PFX)
    for kw, motivo in (({"uf_autor": "XX"}, "uf_invalida"), ({"uf_autor": "SP", "ambiente": "teste"}, "ambiente_invalido")):
        with pytest.raises(ErroDistribuicao) as e:
            ClienteDistribuicao(cert, **kw)
        assert e.value.motivo == motivo
    with pytest.raises(ErroDistribuicao) as e:
        ClienteDistribuicao(cert, "SP").consultar_chave(CHAVE[:-1] + "0")
    assert e.value.motivo == "chave_invalida"
