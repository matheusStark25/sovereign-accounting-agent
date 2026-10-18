"""PGMEI falso para testar o robô: mesma estrutura da tela de identificação real (conferida ao vivo em 2026-10-17:
``#cnpj``, ``#hcaptcha`` com o textarea ``h-captcha-response`` e ``#continuar``) e, depois do captcha, o caminho
Pagamentos -> ano -> Gerar PDF. O servidor só aceita o envio se o token do captcha vier preenchido."""

from __future__ import annotations

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List
from urllib.parse import parse_qs, urlparse

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def pdf_pgmei() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for linha in ("PGMEI - Programa Gerador de DAS do Microempreendedor Individual", "Documento de Arrecadação do Simples Nacional - DAS",
                  "CNPJ 11.222.333/0001-81", "Competência 09/2026", "Valor total 75,90"):
        c.drawString(50, y, linha)
        y -= 16
    c.save()
    return buf.getvalue()


IDENTIFICACAO = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>PGMEI (falso)</title></head><body>
<h1>PGMEI - Programa Gerador de DAS do Microempreendedor Individual</h1>{erro}
<form id="f" action="/Identificacao" method="post">
  <input id="cnpj" name="cnpj" class="form-control" placeholder="__.___.___/____-__">
  <div id="hcaptcha" class="h-captcha" data-sitekey="mock">
    <textarea name="h-captcha-response" style="display:none">{token}</textarea>
    <button id="humano-ok" type="button" onclick="document.querySelector('[name=h-captcha-response]').value='token-do-captcha-resolvido-0123456789'">Resolvi o captcha</button>
  </div>
  <button id="continuar" type="submit" class="btn btn-success">Continuar</button>
</form></body></html>"""

MENU = '<!doctype html><html><body><h1>Menu</h1><a href="/emitir">Emitir Guia</a> <a href="/Pagamentos">Pagamentos</a></body></html>'

PAGAMENTOS = """<!doctype html><html><body><h1>Pagamentos</h1>
<select id="ano"><option>2025</option><option>2026</option></select>
<button id="gerar" type="button" onclick="location.href='/extrato.pdf?ano=' + document.getElementById('ano').value">Gerar PDF</button>
</body></html>"""


class PgmeiFalso:
    def __init__(self, pdf: bytes | None = None, download_malicioso: bool = False, pre_resolvido: bool = False):
        self.pdf, self.malicioso = pdf or pdf_pgmei(), download_malicioso
        self.pre_resolvido = pre_resolvido  # o token do captcha já vem preenchido (para execuções sem janela e sem pessoa)
        self.envios: List[dict] = []  # o que o portal recebeu em cada POST
        self.anos_pedidos: List[str] = []
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
                u = urlparse(self.path)
                if u.path in ("/", "/Identificacao"):
                    return self._enviar(200, "text/html; charset=utf-8", IDENTIFICACAO.format(erro="", token=portal.token()).encode())
                if u.path == "/Pagamentos":
                    return self._enviar(200, "text/html; charset=utf-8", PAGAMENTOS.encode())
                if u.path == "/extrato.pdf":
                    portal.anos_pedidos.append((parse_qs(u.query).get("ano") or [""])[0])
                    corpo = b"isto nao e um pdf" if portal.malicioso else portal.pdf
                    return self._enviar(200, "application/pdf", corpo, {"Content-Disposition": 'attachment; filename="extrato_pgmei.pdf"'})
                self._enviar(404, "text/plain", b"nao encontrado")

            def do_POST(self):
                tam = int(self.headers.get("Content-Length") or 0)
                campos = parse_qs(self.rfile.read(tam).decode())
                portal.envios.append({k: v[0] for k, v in campos.items()})
                if not (campos.get("h-captcha-response") or [""])[0]:
                    erro = '<p class="erro">Resolva o captcha.</p>'
                    return self._enviar(200, "text/html; charset=utf-8", IDENTIFICACAO.format(erro=erro, token="").encode())
                self._enviar(200, "text/html; charset=utf-8", MENU.encode())

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/Identificacao"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def token(self) -> str:
        return "token-do-captcha-resolvido-0123456789" if self.pre_resolvido else ""

    def parar(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
