"""mTLS (TLS mútuo) entre agentes e serviços: os dois lados provam quem são com certificados.

* ``contexto_servidor``: exige certificado de cliente assinado pela CA informada (``CERT_REQUIRED``).
* ``contexto_cliente``: apresenta o certificado do cliente e só aceita servidor assinado pela mesma CA.
* TLS 1.2 no mínimo. Sem CA o contexto não é criado (nada de ``verify=False`` por omissão).
* ``emitir_certificados_dev``: CA, servidor e cliente de curta duração para desenvolvimento e testes
  (em produção os certificados vêm da CA da empresa ou do PKI do Vault).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class ConfigMTLS(ValueError):
    """Certificado, chave ou CA ausente ou ilegível."""


def _exigir(caminho: Optional[str], nome: str) -> str:
    if not caminho or not Path(caminho).is_file():
        raise ConfigMTLS(f"Arquivo de {nome} não encontrado: {caminho!r}")
    return caminho


def contexto_servidor(certfile: str, keyfile: str, cafile: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.load_cert_chain(_exigir(certfile, "certificado do servidor"), _exigir(keyfile, "chave do servidor"))
        ctx.load_verify_locations(cafile=_exigir(cafile, "CA dos clientes"))
    except ssl.SSLError as exc:
        raise ConfigMTLS(f"Certificado ou CA inválidos: {exc}") from exc
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def contexto_cliente(certfile: str, keyfile: str, cafile: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.load_cert_chain(_exigir(certfile, "certificado do cliente"), _exigir(keyfile, "chave do cliente"))
        ctx.load_verify_locations(cafile=_exigir(cafile, "CA do servidor"))
    except ssl.SSLError as exc:
        raise ConfigMTLS(f"Certificado ou CA inválidos: {exc}") from exc
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    return ctx


def create_ssl_context(certfile: Optional[str] = None, keyfile: Optional[str] = None, cafile: Optional[str] = None) -> ssl.SSLContext:
    """Compatibilidade com o nome antigo: contexto de cliente (exige os três arquivos)."""
    return contexto_cliente(certfile or "", keyfile or "", cafile or "")


def cliente_http(certfile: str, keyfile: str, cafile: str, **kw: Any) -> httpx.Client:
    """``httpx.Client`` que fala mTLS (para chamadas entre agentes)."""
    return httpx.Client(verify=contexto_cliente(certfile, keyfile, cafile), **kw)


def opcoes_uvicorn(certfile: str, keyfile: str, cafile: str) -> Dict[str, Any]:
    """Argumentos de ``uvicorn.run`` para servir a API com mTLS obrigatório."""
    _exigir(certfile, "certificado do servidor"), _exigir(keyfile, "chave do servidor"), _exigir(cafile, "CA dos clientes")
    return {"ssl_certfile": certfile, "ssl_keyfile": keyfile, "ssl_ca_certs": cafile, "ssl_cert_reqs": ssl.CERT_REQUIRED}


# -------------------------------------------------------------- certificados de dev
@dataclass(frozen=True)
class CertificadosDev:
    ca: str
    servidor_cert: str
    servidor_key: str
    cliente_cert: str
    cliente_key: str


def _chave() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _nome(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sovereign Accounting Agent (dev)"), x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _pem_chave(k: ec.EllipticCurvePrivateKey) -> bytes:
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _emitir(cn: str, chave, emissor_nome: x509.Name, emissor_chave, dias: int, ca: bool, sans=None, eku=None) -> x509.Certificate:
    agora = dt.datetime.now(dt.timezone.utc)
    b = (
        x509.CertificateBuilder()
        .subject_name(_nome(cn)).issuer_name(emissor_nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(agora - dt.timedelta(minutes=5))
        .not_valid_after(agora + dt.timedelta(days=dias))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
    )
    if ca:
        b = b.add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
    if sans:
        b = b.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    if eku:
        b = b.add_extension(x509.ExtendedKeyUsage(eku), critical=False)
    return b.sign(emissor_chave, hashes.SHA256())


def emitir_certificados_dev(pasta: str | Path, dias: int = 7, nome_servidor: str = "localhost") -> CertificadosDev:
    """CA própria, certificado de servidor (``localhost`` e 127.0.0.1) e de cliente, válidos por ``dias``."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    ca_k, srv_k, cli_k = _chave(), _chave(), _chave()
    ca = _emitir("CA de desenvolvimento", ca_k, _nome("CA de desenvolvimento"), ca_k, dias, ca=True)
    srv = _emitir(
        nome_servidor, srv_k, ca.subject, ca_k, dias, ca=False,
        sans=[x509.DNSName(nome_servidor), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))], eku=[ExtendedKeyUsageOID.SERVER_AUTH],
    )
    cli = _emitir("agente-cliente", cli_k, ca.subject, ca_k, dias, ca=False, eku=[ExtendedKeyUsageOID.CLIENT_AUTH])
    arquivos = {
        "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
        "servidor.pem": srv.public_bytes(serialization.Encoding.PEM), "servidor.key": _pem_chave(srv_k),
        "cliente.pem": cli.public_bytes(serialization.Encoding.PEM), "cliente.key": _pem_chave(cli_k),
    }
    for nome, conteudo in arquivos.items():
        (pasta / nome).write_bytes(conteudo)
        try:
            (pasta / nome).chmod(0o600)
        except OSError:
            pass
    return CertificadosDev(*(str(pasta / n) for n in ("ca.pem", "servidor.pem", "servidor.key", "cliente.pem", "cliente.key")))
