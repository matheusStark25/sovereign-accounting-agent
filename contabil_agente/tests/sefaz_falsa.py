"""SEFAZ falsa para testar o NFeDistribuicaoDFe de verdade: HTTPS com certificado de cliente obrigatório (mTLS), uma "ICP" de
teste que emite um e-CNPJ em .pfx (com o CNPJ no campo da ICP-Brasil, OID 2.16.76.1.3.3) e respostas no formato do
``retDistDFeInt`` (docZip em gzip + base64). Os endereços reais só aceitam certificado ICP-Brasil, que não existe em teste."""

from __future__ import annotations

import base64
import datetime as dt
import gzip
import ipaddress
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SENHA_PFX = "senha-do-pfx-de-teste"
CNPJ_EMPRESA = "11222333000181"


def _chave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _cert(cn, chave, emissor, chave_emissor, ca=False, sans=None, eku=None, dias=30, inicio=None):
    agora = inicio or dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])).issuer_name(emissor)
         .public_key(chave.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(agora - dt.timedelta(days=1)).not_valid_after(agora + dt.timedelta(days=dias))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if sans:
        b = b.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    if eku:
        b = b.add_extension(x509.ExtendedKeyUsage(eku), critical=False)
    return b.sign(chave_emissor, hashes.SHA256())


class IcpDeTeste:
    """CA de teste, certificado do servidor (127.0.0.1) e um e-CNPJ A1 em .pfx."""

    def __init__(self, pasta: Path, vencido: bool = False, cnpj_no_san: bool = True):
        pasta.mkdir(parents=True, exist_ok=True)
        self.ca_chave = _chave()
        nome_ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AC de Teste")])
        self.ca = _cert("AC de Teste", self.ca_chave, nome_ca, self.ca_chave, ca=True)
        srv_k = _chave()
        srv = _cert("127.0.0.1", srv_k, self.ca.subject, self.ca_chave, sans=[x509.IPAddress(ipaddress.ip_address("127.0.0.1"))],
                    eku=[ExtendedKeyUsageOID.SERVER_AUTH])
        self.ca_pem, self.srv_pem, self.srv_key = pasta / "ca.pem", pasta / "srv.pem", pasta / "srv.key"
        self.ca_pem.write_bytes(self.ca.public_bytes(serialization.Encoding.PEM))
        self.srv_pem.write_bytes(srv.public_bytes(serialization.Encoding.PEM))
        self.srv_key.write_bytes(srv_k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.pfx = pasta / "empresa.pfx"
        self.pfx.write_bytes(self.emitir_pfx(f"EMPRESA TESTE LTDA:{CNPJ_EMPRESA}", vencido=vencido, cnpj_no_san=cnpj_no_san))

    def emitir_pfx(self, cn: str, vencido: bool = False, cnpj_no_san: bool = True) -> bytes:
        k = _chave()
        sans = [x509.OtherName(x509.ObjectIdentifier("2.16.76.1.3.3"), b"\x04\x0e" + CNPJ_EMPRESA.encode())] if cnpj_no_san else None
        inicio = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=400) if vencido else None
        c = _cert(cn, k, self.ca.subject, self.ca_chave, sans=sans, eku=[ExtendedKeyUsageOID.CLIENT_AUTH], inicio=inicio)
        return pkcs12.serialize_key_and_certificates(b"empresa", k, c, [self.ca], serialization.BestAvailableEncryption(SENHA_PFX.encode()))


def proc_nfe(chave: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?><nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><NFe><infNFe Id="NFe{chave}" versao="4.00">
<ide><cUF>35</cUF><mod>55</mod><serie>1</serie><nNF>{int(chave[25:34])}</nNF><dhEmi>2026-09-15T10:00:00-03:00</dhEmi></ide>
<emit><CNPJ>{chave[6:20]}</CNPJ><xNome>FORNECEDOR TESTE LTDA</xNome></emit><dest><CNPJ>{CNPJ_EMPRESA}</CNPJ><xNome>EMPRESA TESTE LTDA</xNome></dest>
<total><ICMSTot><vProd>1234.56</vProd><vDesc>0.00</vDesc><vNF>1234.56</vNF></ICMSTot></total></infNFe></NFe>
<protNFe versao="4.00"><infProt><chNFe>{chave}</chNFe><cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe></nfeProc>""".encode()


def res_nfe(chave: str) -> bytes:
    return f'<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><chNFe>{chave}</chNFe><vNF>1234.56</vNF><cSitNFe>1</cSitNFe></resNFe>'.encode()


def _zip(xml: bytes) -> str:
    return base64.b64encode(gzip.compress(xml)).decode()


def resposta(cstat: str, motivo: str, docs: List[tuple] = ()) -> bytes:
    lote = "".join(f'<docZip NSU="{n:015d}" schema="{schema}">{_zip(xml)}</docZip>' for n, (schema, xml) in enumerate(docs, 1))
    lote = f"<loteDistDFeInt>{lote}</loteDistDFeInt>" if lote else ""
    return ('<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body>'
            '<nfeDistDFeInteresseResponse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"><nfeDistDFeInteresseResult>'
            f'<retDistDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><tpAmb>1</tpAmb><verAplic>teste</verAplic><cStat>{cstat}</cStat>'
            f"<xMotivo>{motivo}</xMotivo><dhResp>2026-10-19T10:00:00-03:00</dhResp><ultNSU>000000000000000</ultNSU><maxNSU>000000000000001</maxNSU>"
            f"{lote}</retDistDFeInt></nfeDistDFeInteresseResult></nfeDistDFeInteresseResponse></soap:Body></soap:Envelope>").encode()


class SefazFalsa:
    """``modo``: proc (nota completa), resumo (só resNFe), nenhum (137), consumo_indevido (656), outra_nota (XML de outra chave)."""

    def __init__(self, icp: IcpDeTeste, modo: str = "proc"):
        self.modo, self.pedidos = modo, []  # type: str, List[Dict[str, str]]
        sefaz = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                titular = dict(x[0] for x in self.connection.getpeercert().get("subject", ()))
                sefaz.pedidos.append({"corpo": corpo.decode(), "tipo": self.headers.get("Content-Type", ""), "certificado": titular.get("commonName", "")})
                chave = corpo.decode().split("<chNFe>")[1].split("</chNFe>")[0]
                saida = {
                    "proc": lambda: resposta("138", "Documento localizado", [("procNFe_v4.00.xsd", proc_nfe(chave))]),
                    "resumo": lambda: resposta("138", "Documento localizado", [("resNFe_v1.01.xsd", res_nfe(chave))]),
                    "nenhum": lambda: resposta("137", "Nenhum documento localizado"),
                    "consumo_indevido": lambda: resposta("656", "Rejeicao: Consumo Indevido"),
                    "outra_nota": lambda: resposta("138", "Documento localizado", [("procNFe_v4.00.xsd", proc_nfe("3" * 43 + "1"))]),
                }[sefaz.modo]()
                self.send_response(200)
                self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(saida)))
                self.end_headers()
                self.wfile.write(saida)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(icp.srv_pem), str(icp.srv_key))
        ctx.load_verify_locations(cafile=str(icp.ca_pem))
        ctx.verify_mode = ssl.CERT_REQUIRED  # como a SEFAZ: sem certificado de cliente, nada feito
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.socket = ctx.wrap_socket(self.srv.socket, server_side=True)
        self.url = f"https://127.0.0.1:{self.srv.server_address[1]}/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def parar(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
