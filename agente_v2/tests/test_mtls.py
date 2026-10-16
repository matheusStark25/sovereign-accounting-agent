"""mTLS de verdade: handshake TLS local com certificados emitidos no teste."""

import socket
import ssl
import threading

import pytest

from agente_v2 import mtls


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    return mtls.emitir_certificados_dev(tmp_path_factory.mktemp("pki"))


@pytest.fixture()
def servidor(certs):
    """Servidor TLS que exige certificado de cliente e responde 'oi <CN do cliente>'."""
    ctx = mtls.contexto_servidor(certs.servidor_cert, certs.servidor_key, certs.ca)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    porta = sock.getsockname()[1]
    resultados = []

    def servir():
        while True:
            try:
                bruto, _ = sock.accept()
            except OSError:
                return
            try:
                with ctx.wrap_socket(bruto, server_side=True) as tls:
                    cert = tls.getpeercert()
                    cn = dict(x[0] for x in cert["subject"])["commonName"]
                    tls.recv(16)
                    tls.sendall(f"oi {cn}".encode())
                    resultados.append(cn)
            except (ssl.SSLError, OSError):
                resultados.append("recusado")
            finally:
                bruto.close()

    threading.Thread(target=servir, daemon=True).start()
    yield porta, resultados
    sock.close()


def conectar(porta, ctx, hostname="localhost"):
    with socket.create_connection(("127.0.0.1", porta), timeout=5) as s:
        with ctx.wrap_socket(s, server_hostname=hostname) as tls:
            tls.sendall(b"ping")
            resposta = tls.recv(64)
            if not resposta:  # TLS 1.3: a recusa do certificado de cliente chega como conexão encerrada
                raise ConnectionError("o servidor encerrou a conexão (certificado de cliente recusado)")
            return resposta.decode()


def test_cliente_com_certificado_valido_e_aceito(servidor, certs):
    porta, resultados = servidor
    ctx = mtls.contexto_cliente(certs.cliente_cert, certs.cliente_key, certs.ca)
    assert conectar(porta, ctx) == "oi agente-cliente" and resultados == ["agente-cliente"]


def test_cliente_sem_certificado_e_recusado(servidor, certs):
    porta, _ = servidor
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(certs.ca)
    with pytest.raises((ssl.SSLError, ConnectionError, OSError)):
        conectar(porta, ctx)


def test_cliente_com_certificado_de_outra_ca_e_recusado(servidor, certs, tmp_path):
    porta, _ = servidor
    outra = mtls.emitir_certificados_dev(tmp_path / "outra")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(certs.ca)
    ctx.load_cert_chain(outra.cliente_cert, outra.cliente_key)
    with pytest.raises((ssl.SSLError, ConnectionError, OSError)):
        conectar(porta, ctx)


def test_cliente_nao_aceita_servidor_de_outra_ca(servidor, certs, tmp_path):
    porta, _ = servidor
    outra = mtls.emitir_certificados_dev(tmp_path / "outra2")
    ctx = mtls.contexto_cliente(certs.cliente_cert, certs.cliente_key, outra.ca)  # confia em outra CA
    with pytest.raises(ssl.SSLCertVerificationError):
        conectar(porta, ctx)


def test_cliente_confere_o_nome_do_servidor(servidor, certs):
    porta, _ = servidor
    ctx = mtls.contexto_cliente(certs.cliente_cert, certs.cliente_key, certs.ca)
    with pytest.raises(ssl.SSLCertVerificationError):
        conectar(porta, ctx, hostname="outro.exemplo.com")


def test_servidor_exige_cert_e_tls_minimo_1_2(certs):
    ctx = mtls.contexto_servidor(certs.servidor_cert, certs.servidor_key, certs.ca)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    cli = mtls.contexto_cliente(certs.cliente_cert, certs.cliente_key, certs.ca)
    assert cli.verify_mode == ssl.CERT_REQUIRED and cli.check_hostname is True


def test_arquivo_ausente_ou_invalido_levanta_erro_claro(certs, tmp_path):
    with pytest.raises(mtls.ConfigMTLS):
        mtls.contexto_servidor("nao_existe.pem", certs.servidor_key, certs.ca)
    lixo = tmp_path / "lixo.pem"
    lixo.write_text("isto não é um certificado")
    with pytest.raises(mtls.ConfigMTLS):
        mtls.contexto_cliente(str(lixo), certs.cliente_key, certs.ca)
    with pytest.raises(mtls.ConfigMTLS):
        mtls.create_ssl_context()  # sem arquivos: nada de verify=False por omissão


def test_opcoes_do_uvicorn_exigem_certificado_de_cliente(certs):
    o = mtls.opcoes_uvicorn(certs.servidor_cert, certs.servidor_key, certs.ca)
    assert o["ssl_cert_reqs"] == ssl.CERT_REQUIRED and o["ssl_ca_certs"] == certs.ca


def test_certificados_de_dev_tem_ca_servidor_e_cliente_com_usos_corretos(certs):
    from cryptography import x509
    from cryptography.x509.oid import ExtendedKeyUsageOID

    ler = lambda p: x509.load_pem_x509_certificate(open(p, "rb").read())  # noqa: E731
    assert ler(certs.ca).extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert ExtendedKeyUsageOID.SERVER_AUTH in ler(certs.servidor_cert).extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.CLIENT_AUTH in ler(certs.cliente_cert).extensions.get_extension_for_class(x509.ExtendedKeyUsage).value


def test_httpx_com_mtls_contra_servidor_https_real(certs):
    """Sobe um servidor HTTPS (http.server) com mTLS e chama com o cliente httpx do módulo."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"mtls-ok")

    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.socket = mtls.contexto_servidor(certs.servidor_cert, certs.servidor_key, certs.ca).wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        porta = srv.server_address[1]
        with mtls.cliente_http(certs.cliente_cert, certs.cliente_key, certs.ca) as c:
            assert c.get(f"https://localhost:{porta}/").text == "mtls-ok"
        import httpx

        with httpx.Client(verify=ssl.create_default_context(cafile=certs.ca)) as sem_cert, pytest.raises(httpx.HTTPError):
            sem_cert.get(f"https://localhost:{porta}/")
    finally:
        srv.shutdown()
        srv.server_close()
