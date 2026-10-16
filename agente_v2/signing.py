"""Assinatura digital de XML (XML-DSig enveloped, RSA-SHA256), no padrão exigido pelo eSocial e pela NF-e.

* O XML é lido com ``lxml`` sem resolver entidades nem acessar rede (sem XXE).
* Certificado e chave A1 (PEM) vêm do Vault por ``assinar_xml_do_cofre``; a chave não é gravada em disco.
* Certificado A3 (token/cartão) não é suportado: exige PKCS#11 do fabricante.
* ``verificar_xml`` confere a assinatura contra o certificado esperado (nunca contra o que vem dentro do XML).
"""

from __future__ import annotations

from typing import Any, Optional, Union

from lxml import etree
from signxml import XMLSigner, XMLVerifier, methods
from signxml.exceptions import InvalidSignature

Pem = Union[str, bytes]


class AssinaturaInvalida(Exception):
    pass


def _pem(valor: Pem) -> bytes:
    return valor.encode("ascii") if isinstance(valor, str) else valor


def _ler_xml(xml: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False)
    try:
        raiz = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError as exc:
        raise AssinaturaInvalida(f"XML inválido: {exc}") from exc
    if raiz.getroottree().docinfo.doctype:
        raise AssinaturaInvalida("XML com DOCTYPE não é aceito para assinatura.")
    return raiz


def assinar_xml(xml: bytes, cert_pem: Pem, key_pem: Pem, referencia: Optional[str] = None) -> bytes:
    """Assina o XML (assinatura envelopada). ``referencia`` assina só o elemento com esse atributo Id (eSocial/NF-e)."""
    raiz = _ler_xml(xml)
    assinador = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    try:
        assinado = assinador.sign(raiz, key=_pem(key_pem), cert=_pem(cert_pem), reference_uri=f"#{referencia}" if referencia else None)
    except Exception as exc:  # noqa: BLE001 - chave/certificado inválidos ou incompatíveis
        raise AssinaturaInvalida(f"Não consegui assinar: {type(exc).__name__}: {exc}") from exc
    return etree.tostring(assinado, xml_declaration=True, encoding="UTF-8")


def verificar_xml(xml_assinado: bytes, cert_pem: Pem) -> bool:
    """``True`` se a assinatura confere com o certificado informado; ``False`` caso contrário (nunca levanta por assinatura ruim)."""
    try:
        raiz = _ler_xml(xml_assinado)
        XMLVerifier().verify(raiz, x509_cert=_pem(cert_pem).decode("ascii"), expect_references=True)
        return True
    except (InvalidSignature, AssinaturaInvalida, etree.XMLSyntaxError):
        return False
    except Exception:  # noqa: BLE001 - assinatura malformada, algoritmo fraco, etc.
        return False


def assinar_xml_do_cofre(xml: bytes, vault: Any, path: str = "certs", chave_cert: str = "a1_cert", chave_priv: str = "a1_key", referencia: Optional[str] = None) -> bytes:
    """Busca o par A1 no Vault (KV) e assina. Levanta ``SegredoIndisponivel`` se o cofre falhar."""
    cert = vault.get_certificate(path, chave_cert)
    chave = vault.get_private_key(path, chave_priv)
    return assinar_xml(xml, cert, chave, referencia)


def sign_xml(xml_bytes: bytes, vault: Any, cert_path: str = "a1_cert", key_path: str = "a1_key", secret_path: str = "certs") -> bytes:
    """Nome antigo: assina com o par A1 guardado no Vault."""
    return assinar_xml_do_cofre(xml_bytes, vault, secret_path, cert_path, key_path)
