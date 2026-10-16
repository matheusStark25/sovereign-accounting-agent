from __future__ import annotations
 
from .vault_client import VaultClient

try:
    from signxml import XMLSigner
except Exception:
    XMLSigner = None


def sign_xml(
    xml_bytes: bytes, vault: VaultClient, cert_path: str, key_path: str
) -> bytes:
    """Sign XML using signxml and private key stored/accessed via Vault.

    The VaultClient abstraction should provide a way to retrieve PEMs for cert/key.
    """
    cert_pem = vault.get_certificate("secret/certs", cert_path)
    key_pem = vault.get_private_key("secret/certs", key_path)
    if XMLSigner is None:
        raise RuntimeError("signxml is not installed")
    if not cert_pem or not key_pem:
        raise RuntimeError("certificate or key not available in Vault")

    # signxml expects parsed element; caller handles parsing/encoding
    from lxml import etree

    # Handle A3-style keys (hardware/token) if a reference dict is returned
    if isinstance(key_pem, dict):
        # Platform-specific hardware signing not implemented here
        raise NotImplementedError(
            "A3/hardware signing via Vault reference not implemented"
        )

    root = etree.fromstring(xml_bytes)
    signer = XMLSigner()
    signed = signer.sign(root, key=key_pem, cert=cert_pem)
    return etree.tostring(signed)
