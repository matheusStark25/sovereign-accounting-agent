"""Portal de FGTS falso para testar o robô: formulário com CPF, captcha de mentira e extrato em PDF."""

from __future__ import annotations

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PIS_VALIDO = "12345678919"


def pdf_extrato(saldo: str = "12.000,00") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for linha in ("Extrato analítico do FGTS - conta vinculada", f"PIS 123.45678.91-9", f"Saldo total {saldo}", "CNPJ 11.222.333/0001-81"):
        c.drawString(50, y, linha)
        y -= 16
    c.save()
    return buf.getvalue()


PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Portal FGTS (falso)</title></head><body>
<h1>Consulta FGTS</h1>
{desafio}
<form id="f" action="/consulta" method="post" onsubmit="return !document.getElementById('captcha');">
  <input id="cpf" name="cpf" placeholder="CPF"><button type="submit">Consultar</button>
</form></body></html>"""

CAPTCHA = """<div id="captcha" data-sitekey="mock"><p>Confirme que você não é um robô</p>
<button id="humano-ok" type="button" onclick="document.getElementById('captcha').remove()">Não sou um robô</button></div>"""


class PortalFalso:
    def __init__(self, com_captcha: bool = True, pdf: bytes | None = None, download_malicioso: bool = False, redireciona: str | None = None):
        self.com_captcha, self.pdf, self.malicioso, self.redireciona = com_captcha, pdf or pdf_extrato(), download_malicioso, redireciona
        self.cpfs_recebidos: List[str] = []
        portal = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _enviar(self, status, tipo, corpo, extra=None):
                self.send_response(status)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self):
                if self.path == "/":
                    if portal.redireciona:
                        return self._enviar(302, "text/plain", b"", {"Location": portal.redireciona})
                    return self._enviar(200, "text/html; charset=utf-8", PAGINA.format(desafio=CAPTCHA if portal.com_captcha else "").encode())
                if self.path == "/extrato.pdf":
                    corpo = b"isto nao e um pdf" if portal.malicioso else portal.pdf
                    return self._enviar(200, "application/pdf", corpo, {"Content-Disposition": 'attachment; filename="extrato.pdf"'})
                self._enviar(404, "text/plain", b"nao encontrado")

            def do_POST(self):
                tam = int(self.headers.get("Content-Length") or 0)
                corpo = self.rfile.read(tam).decode()
                portal.cpfs_recebidos.append(corpo)
                html = '<!doctype html><html><body><h1>Resultado</h1><a href="/extrato.pdf">Extrato</a></body></html>'
                self._enviar(200, "text/html; charset=utf-8", html.encode())

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def parar(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
