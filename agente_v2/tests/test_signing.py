"""Assinatura XML-DSig: assina, verifica e detecta adulteração, certificado trocado e XML perigoso."""

import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from agente_v2.signing import AssinaturaInvalida, assinar_xml, assinar_xml_do_cofre, sign_xml, verificar_xml
from agente_v2.vault_client import SegredoIndisponivel, VaultClient


def par_rsa(cn="Empresa Teste (A1 de teste)"):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(agora - dt.timedelta(minutes=5))
        .not_valid_after(agora + dt.timedelta(days=30)).sign(chave, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM).decode(),
        chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
    )


@pytest.fixture(scope="module")
def a1():
    return par_rsa()


XML = (
    '<eSocial xmlns="http://www.esocial.gov.br/schema/evt/evtRemun/v_S_01_02_00"><evtRemun Id="ID123">'
    "<ideTrabalhador><cpfTrab>52998224725</cpfTrab></ideTrabalhador><vrRubr>3000.00</vrRubr></evtRemun></eSocial>"
).encode()


def test_assina_e_verifica(a1):
    cert, chave = a1
    assinado = assinar_xml(XML, cert, chave)
    assert b"<ds:Signature" in assinado or b"<Signature" in assinado
    assert b"rsa-sha256" in assinado and b"xmldsig-more#rsa-sha256" in assinado or b"rsa-sha256" in assinado
    assert verificar_xml(assinado, cert) is True


def test_adulterar_o_conteudo_quebra_a_assinatura(a1):
    cert, chave = a1
    assinado = assinar_xml(XML, cert, chave)
    assert verificar_xml(assinado.replace(b"3000.00", b"9000.00"), cert) is False
    assert verificar_xml(assinado.replace(b"52998224725", b"11144477735"), cert) is False


def test_certificado_diferente_nao_valida(a1):
    cert, chave = a1
    outro_cert, _ = par_rsa("Outra empresa")
    assert verificar_xml(assinar_xml(XML, cert, chave), outro_cert) is False


def test_assinatura_so_de_um_elemento_por_id(a1):
    cert, chave = a1
    assinado = assinar_xml(XML, cert, chave, referencia="ID123")
    assert b'URI="#ID123"' in assinado and verificar_xml(assinado, cert)


def test_xml_sem_assinatura_ou_quebrado_nao_valida(a1):
    cert, _ = a1
    assert verificar_xml(XML, cert) is False
    assert verificar_xml(b"<a><b></a>", cert) is False
    assert verificar_xml(b"", cert) is False


def test_xml_com_doctype_ou_entidade_externa_e_recusado(a1):
    cert, chave = a1
    xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    with pytest.raises(AssinaturaInvalida):
        assinar_xml(xxe, cert, chave)
    assert verificar_xml(xxe, cert) is False


def test_chave_que_nao_combina_com_o_certificado_nao_gera_assinatura_valida(a1):
    cert, _ = a1
    _, chave_de_outro = par_rsa("Outro")
    try:
        assinado = assinar_xml(XML, cert, chave_de_outro)
    except AssinaturaInvalida:
        return
    assert verificar_xml(assinado, cert) is False


def test_chave_invalida_vira_erro_claro(a1):
    cert, _ = a1
    with pytest.raises(AssinaturaInvalida):
        assinar_xml(XML, cert, "não é uma chave")


def test_assina_com_o_par_a1_guardado_no_vault(a1):
    cert, chave = a1
    vault = VaultClient.em_memoria({"certs": {"a1_cert": cert, "a1_key": chave}})
    assinado = assinar_xml_do_cofre(XML, vault)
    assert verificar_xml(assinado, cert)
    assert verificar_xml(sign_xml(XML, vault), cert)


def test_sem_o_certificado_no_vault_nao_assina(a1):
    vault = VaultClient.em_memoria({"certs": {}})
    with pytest.raises(SegredoIndisponivel):
        assinar_xml_do_cofre(XML, vault)


def test_assina_um_evento_esocial_do_pipeline(a1):
    """Os mesmos bytes de eSocial que o pipeline classifica podem ser assinados e a assinatura confere."""
    from contabil_agente.documentos.processador import processar_documento
    from contabil_agente.tests import amostras_documentos as am

    cert, chave = a1
    assinado = assinar_xml(am.ESOCIAL_REMUN, cert, chave)
    assert verificar_xml(assinado, cert)
    assert processar_documento(assinado).tipo == "ESOCIAL_XML"
