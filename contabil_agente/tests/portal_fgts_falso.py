"""Portal de FGTS falso para testar o robô: formulário com CPF, captcha de mentira e extrato em PDF.

``variante`` simula o que acontece quando o site muda ou se comporta mal:
* ``padrao``: o formulário de sempre;
* ``layout_novo``: ids, nomes e textos renomeados (os seletores configurados deixam de valer);
* ``tardia``: o formulário só aparece 2 s depois, montado por JavaScript;
* ``iframe``: o formulário (e o resultado) ficam dentro de um iframe;
* ``campo_desconhecido``: dois campos de texto sem rótulo nenhum (o robô não tem como adivinhar qual é o CPF);
* ``link_sem_pistas``: o link do PDF não tem texto nem endereço reconhecíveis;
* ``bloqueado``: ao enviar, o portal responde que o comportamento é de robô (como o PGMEI real, erro 13896).
"""

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
    for linha in ("Extrato analítico do FGTS - conta vinculada", "PIS 123.45678.91-9", f"Saldo total {saldo}", "CNPJ 11.222.333/0001-81"):
        c.drawString(50, y, linha)
        y -= 16
    c.save()
    return buf.getvalue()


FORM_PADRAO = """<form id="f" action="/consulta" method="post" onsubmit="return !document.getElementById('captcha');">
  <input id="cpf" name="cpf" placeholder="CPF"><button type="submit">Consultar</button>
</form>"""

FORM_NOVO = """<form id="formulario-x" action="/consulta" method="post" onsubmit="return !document.getElementById('captcha');">
  <input id="campo-documento" name="doc" placeholder="Digite seu CPF"><button id="btn-x" type="submit">Consultar</button>
</form>"""

FORM_DESCONHECIDO = """<form id="f" action="/consulta" method="post">
  <input name="x1"><input name="x2"><button type="submit">Consultar</button>
</form>"""

PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Portal FGTS (falso)</title></head><body>
<h1>Consulta FGTS</h1>
{desafio}
{corpo}</body></html>"""

CAPTCHA = """<div id="captcha" data-sitekey="mock"><p>Confirme que você não é um robô</p>
<button id="humano-ok" type="button" onclick="document.getElementById('captcha').remove()">Não sou um robô</button></div>"""

TARDIA = """<div id="raiz">Carregando…</div>
<script>setTimeout(function () { document.getElementById('raiz').innerHTML = %s; }, 2000);</script>"""

BLOQUEIO = '<!doctype html><html><body><p>\n13896 - Impedido por proteção Captcha. Comportamento de Robô.</p></body></html>'

LINKS = {
    "padrao": '<a href="/extrato.pdf">Extrato</a>',
    "layout_novo": '<a href="/extrato?formato=pdf">Comprovante em PDF</a>',
    "link_sem_pistas": '<a id="x" href="/arquivo?id=7">Clique aqui</a>',
}


class PortalFalso:
    def __init__(self, com_captcha: bool = True, pdf: bytes | None = None, download_malicioso: bool = False,
                 redireciona: str | None = None, variante: str = "padrao"):
        self.com_captcha, self.pdf, self.malicioso, self.redireciona = com_captcha, pdf or pdf_extrato(), download_malicioso, redireciona
        self.variante = variante
        self.cpfs_recebidos: List[str] = []
        self.visitas_raiz = 0
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

            def _formulario(self):
                v = portal.variante
                return {"layout_novo": FORM_NOVO, "campo_desconhecido": FORM_DESCONHECIDO}.get(v, FORM_PADRAO)

            def _pdf(self):
                corpo = b"isto nao e um pdf" if portal.malicioso else portal.pdf
                return self._enviar(200, "application/pdf", corpo, {"Content-Disposition": 'attachment; filename="extrato.pdf"'})

            def do_GET(self):
                caminho = self.path.split("?")[0]
                if caminho == "/":
                    portal.visitas_raiz += 1
                    if portal.redireciona:
                        return self._enviar(302, "text/plain", b"", {"Location": portal.redireciona})
                    desafio = CAPTCHA if portal.com_captcha else ""
                    if portal.variante == "tardia":
                        corpo = TARDIA % repr(FORM_PADRAO.replace("\n", " "))
                    elif portal.variante == "iframe":
                        corpo = '<iframe src="/form" width="600" height="300"></iframe>'
                    else:
                        corpo = self._formulario()
                    return self._enviar(200, "text/html; charset=utf-8", PAGINA.format(desafio=desafio, corpo=corpo).encode())
                if caminho == "/form":
                    return self._enviar(200, "text/html; charset=utf-8", PAGINA.format(desafio="", corpo=FORM_PADRAO).encode())
                if caminho in ("/extrato.pdf", "/extrato", "/arquivo"):
                    return self._pdf()
                self._enviar(404, "text/plain", b"nao encontrado")

            def do_POST(self):
                tam = int(self.headers.get("Content-Length") or 0)
                corpo = self.rfile.read(tam).decode()
                portal.cpfs_recebidos.append(corpo)
                if portal.variante == "bloqueado":
                    return self._enviar(200, "text/html; charset=utf-8", BLOQUEIO.encode())
                link = LINKS.get(portal.variante, LINKS["padrao"])
                html = f'<!doctype html><html><body><h1>Resultado</h1>{link}</body></html>'
                self._enviar(200, "text/html; charset=utf-8", html.encode())

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def parar(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
