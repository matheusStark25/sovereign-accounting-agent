"""XML completo da NF-e pelo canal oficial: o web service NFeDistribuicaoDFe do Ambiente Nacional, com o certificado digital A1
(.pfx) da empresa. Sem navegador e sem captcha.

A SEFAZ só entrega a nota a quem aparece nela (destinatário, emitente, transportador ou autorizado no XML) e identifica a
empresa pelo certificado de cliente da conexão TLS. Para quem é destinatário, às vezes ela entrega primeiro só o resumo
(``resNFe``) até a empresa registrar a manifestação "Ciência da Operação"; o cliente diz isso em vez de fingir que baixou.

Conferido em 2026-10-19: os endereços de produção e de homologação estão no ar, com TLS válido (AC SERPRO), e respondem 403 a
quem chega sem certificado de cliente.

A chave privada do certificado nunca vai em claro para o disco: para a conexão ela é gravada cifrada, com uma senha aleatória,
numa pasta temporária que é apagada logo depois.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import re
import secrets
import shutil
import ssl
import tempfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional, Tuple, Union
from xml.sax.saxutils import escape

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from defusedxml import ElementTree as ET

from contabil_agente.documentos.validadores import so_digitos, validar_chave_acesso, validar_cnpj, validar_cpf

URLS = {
    "producao": "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    "homologacao": "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}
ACAO_SOAP = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"
OID_CNPJ_ICP = "2.16.76.1.3.3"  # ICP-Brasil: CNPJ do titular no certificado e-CNPJ (outro nome no SubjectAltName)
LIMITE_XML = 5 * 1024 * 1024  # um XML de NF-e descompactado nunca chega perto disso (proteção contra bomba de compactação)
UF_IBGE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17", "MA": "21", "PI": "22", "CE": "23", "RN": "24",
    "PB": "25", "PE": "26", "AL": "27", "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41", "SC": "42",
    "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}
MENSAGENS = {
    "137": "a SEFAZ não tem documento desta chave para o CNPJ do certificado (a empresa precisa aparecer na nota)",
    "656": "consumo indevido: a SEFAZ bloqueou consultas deste CNPJ por um tempo (em geral 1 hora); espere antes de tentar de novo",
    "593": "o CNPJ informado não é o do certificado",
    "641": "a chave de acesso não foi encontrada para este interessado",
}


class ErroDistribuicao(RuntimeError):
    def __init__(self, motivo: str, detalhe: str = "", cstat: str = ""):
        super().__init__(f"{motivo}: {detalhe}" if detalhe else motivo)
        self.motivo, self.cstat = motivo, cstat


@dataclass
class DocumentoDFe:
    nsu: str
    schema: str
    xml: bytes

    @property
    def tipo(self) -> str:
        return self.schema.split("_")[0]  # procNFe, resNFe, procEventoNFe, resEvento


@dataclass
class RespostaDFe:
    cstat: str
    motivo: str
    ult_nsu: str = ""
    max_nsu: str = ""
    documentos: List[DocumentoDFe] = field(default_factory=list)


@dataclass
class XMLBaixado:
    caminho: str
    sha256: str
    tamanho: int
    chave: str


def cnpj_do_certificado(cert: x509.Certificate) -> Optional[str]:
    """CNPJ do titular: o campo da ICP-Brasil no SubjectAltName ou, na falta dele, o final do nome (``EMPRESA LTDA:11222333000181``)."""
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for nome in san.get_values_for_type(x509.OtherName):
            if nome.type_id.dotted_string == OID_CNPJ_ICP:
                achado = re.search(rb"\d{14}", nome.value)
                if achado and validar_cnpj(achado.group(0).decode()):
                    return achado.group(0).decode()
    except x509.ExtensionNotFound:
        pass
    for atributo in cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME):
        achado = re.search(r":(\d{14})$", str(atributo.value))
        if achado and validar_cnpj(achado.group(1)):
            return achado.group(1)
    return None


class CertificadoA1:
    """Certificado A1 (.pfx/.p12) com a senha. Recusa certificado vencido ou sem chave privada."""

    def __init__(self, pfx: Union[str, Path, bytes], senha: str):
        dados = pfx if isinstance(pfx, bytes) else Path(pfx).read_bytes()
        try:
            chave, cert, cadeia = pkcs12.load_key_and_certificates(dados, senha.encode("utf-8") if senha else None)
        except ValueError as exc:
            raise ErroDistribuicao("certificado_invalido", "o arquivo não é um .pfx válido ou a senha está errada") from exc
        if chave is None or cert is None:
            raise ErroDistribuicao("certificado_invalido", "o .pfx não tem a chave privada e o certificado")
        self._chave, self.cert, self._cadeia = chave, cert, list(cadeia or [])
        self.validade = cert.not_valid_after_utc
        if self.validade < datetime.now(timezone.utc):
            raise ErroDistribuicao("certificado_vencido", f"venceu em {self.validade:%d/%m/%Y}")
        self.cnpj = cnpj_do_certificado(cert)

    @contextlib.contextmanager
    def contexto_tls(self, verificar: Union[bool, str] = True) -> Iterator[ssl.SSLContext]:
        """Contexto TLS com o certificado de cliente. A chave vai cifrada (senha aleatória) para uma pasta temporária apagada no fim."""
        pasta = tempfile.mkdtemp(prefix="cert_a1_")
        try:
            senha = secrets.token_urlsafe(24).encode()
            caminho_cert, caminho_chave = os.path.join(pasta, "cert.pem"), os.path.join(pasta, "chave.pem")
            with open(caminho_cert, "wb") as f:
                for c in [self.cert, *self._cadeia]:
                    f.write(c.public_bytes(serialization.Encoding.PEM))
            with open(caminho_chave, "wb") as f:
                f.write(self._chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.BestAvailableEncryption(senha)))
            if isinstance(verificar, str):
                ctx = ssl.create_default_context(cafile=verificar)
            else:
                import certifi

                ctx = ssl.create_default_context(cafile=certifi.where())
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(caminho_cert, caminho_chave, password=senha)
            yield ctx
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


def montar_pedido(documento: str, uf_autor: str, ambiente: str, chave: str) -> bytes:
    """Envelope SOAP 1.2 do ``distDFeInt`` (versão 1.01) pedindo uma chave (``consChNFe``)."""
    digitos = so_digitos(documento)
    campo = "CNPJ" if len(digitos) == 14 else "CPF"
    tp_amb = "1" if ambiente == "producao" else "2"
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap12="http://www.w3.org/2003/05/soap-envelope"><soap12:Body>'
        '<nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"><nfeDadosMsg>'
        '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
        f"<tpAmb>{tp_amb}</tpAmb><cUFAutor>{escape(uf_autor)}</cUFAutor><{campo}>{digitos}</{campo}>"
        f"<consChNFe><chNFe>{so_digitos(chave)}</chNFe></consChNFe>"
        "</distDFeInt></nfeDadosMsg></nfeDistDFeInteresse></soap12:Body></soap12:Envelope>"
    ).encode("utf-8")


def _descompactar(base64_gzip: str) -> bytes:
    bruto = base64.b64decode(base64_gzip or "", validate=False)
    d = zlib.decompressobj(wbits=31)  # gzip
    xml = d.decompress(bruto, LIMITE_XML + 1)
    if len(xml) > LIMITE_XML or d.unconsumed_tail:
        raise ErroDistribuicao("documento_grande_demais", "o documento descompactado passa de 5 MB")
    return xml


def ler_resposta(conteudo: bytes) -> RespostaDFe:
    """Lê o ``retDistDFeInt`` de dentro da resposta SOAP (XML lido com defusedxml: sem entidades externas)."""
    try:
        raiz = ET.fromstring(conteudo)
    except Exception as exc:  # noqa: BLE001 - qualquer XML malformado ou perigoso
        raise ErroDistribuicao("resposta_invalida", "a SEFAZ respondeu algo que não é XML válido") from exc
    ret = raiz.find(".//{*}retDistDFeInt")
    if ret is None:
        falha = raiz.find(".//{*}Text")
        raise ErroDistribuicao("resposta_invalida", (falha.text or "")[:200] if falha is not None else "sem retDistDFeInt")

    def texto(tag: str) -> str:
        el = ret.find(f"{{*}}{tag}")
        return (el.text or "").strip() if el is not None else ""

    docs = [DocumentoDFe(z.get("NSU", ""), z.get("schema", ""), _descompactar(z.text or "")) for z in ret.findall(".//{*}docZip")]
    return RespostaDFe(texto("cStat"), texto("xMotivo"), texto("ultNSU"), texto("maxNSU"), docs)


class ClienteDistribuicao:
    def __init__(self, certificado: CertificadoA1, uf_autor: str, ambiente: str = "producao", documento: Optional[str] = None,
                 url: Optional[str] = None, verificar: Union[bool, str] = True, timeout_s: float = 60.0):
        if ambiente not in URLS:
            raise ErroDistribuicao("ambiente_invalido", "use producao ou homologacao")
        uf = UF_IBGE.get(str(uf_autor).upper(), str(uf_autor))
        if uf not in UF_IBGE.values():
            raise ErroDistribuicao("uf_invalida", "informe a UF da empresa (sigla, como SP, ou o código IBGE)")
        doc = so_digitos(documento or certificado.cnpj or "")
        if not (validar_cnpj(doc) if len(doc) == 14 else validar_cpf(doc)):
            raise ErroDistribuicao("cnpj_ausente", "não achei o CNPJ no certificado; informe o CNPJ da empresa")
        self.certificado, self.uf, self.ambiente, self.documento = certificado, uf, ambiente, doc
        self.url, self.verificar, self.timeout_s = url or URLS[ambiente], verificar, timeout_s

    def consultar_chave(self, chave: str) -> RespostaDFe:
        if not validar_chave_acesso(chave):
            raise ErroDistribuicao("chave_invalida", "informe os 44 dígitos da chave de acesso, com o dígito verificador correto")
        pedido = montar_pedido(self.documento, self.uf, self.ambiente, chave)
        cabecalho = {"Content-Type": f'application/soap+xml; charset=utf-8; action="{ACAO_SOAP}"'}
        with self.certificado.contexto_tls(self.verificar) as ctx:
            try:
                with httpx.Client(verify=ctx, timeout=self.timeout_s) as http:
                    r = http.post(self.url, content=pedido, headers=cabecalho)
            except httpx.HTTPError as exc:
                raise ErroDistribuicao("sefaz_inacessivel", type(exc).__name__) from exc
        if r.status_code == 403:
            raise ErroDistribuicao("certificado_recusado", "a SEFAZ recusou o certificado de cliente (403)")
        if r.status_code != 200 and b"retDistDFeInt" not in r.content:
            raise ErroDistribuicao(f"http_{r.status_code}", "resposta inesperada da SEFAZ")
        return ler_resposta(r.content)

    def baixar_xml(self, chave: str, pasta: Union[str, Path]) -> Tuple[XMLBaixado, RespostaDFe]:
        """Baixa o XML autorizado (``procNFe``) da chave e grava ``nfe_<chave>.xml`` (0600). Sem ele, diz exatamente o porquê."""
        digitos = so_digitos(chave)
        resp = self.consultar_chave(digitos)
        if resp.cstat != "138":
            raise ErroDistribuicao(f"cstat_{resp.cstat}", MENSAGENS.get(resp.cstat, resp.motivo or "sem motivo"), resp.cstat)
        proc = [d for d in resp.documentos if d.tipo == "procNFe"]
        if not proc:
            if any(d.tipo == "resNFe" for d in resp.documentos):
                raise ErroDistribuicao("so_resumo", "a SEFAZ entregou só o resumo da nota: registre a manifestação 'Ciência da Operação' "
                                                    "e consulte de novo para receber o XML completo", resp.cstat)
            raise ErroDistribuicao("sem_xml_da_nota", "a resposta não trouxe o XML da nota", resp.cstat)
        xml = proc[0].xml
        if f'Id="NFe{digitos}"'.encode() not in xml and f"<chNFe>{digitos}</chNFe>".encode() not in xml:
            raise ErroDistribuicao("xml_de_outra_nota", "o XML recebido não é da chave pedida", resp.cstat)
        destino = Path(pasta) / f"nfe_{digitos}.xml"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(xml)
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
        return XMLBaixado(str(destino), hashlib.sha256(xml).hexdigest(), len(xml), digitos), resp
