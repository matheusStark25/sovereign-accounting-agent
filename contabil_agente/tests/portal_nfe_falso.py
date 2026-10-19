"""Consultas de NF-e, CT-e e NFC-e (SP) falsas para testar o robô: os formulários têm os mesmos ids da tela real (conferidos ao
vivo em 2026-10-19): o hCaptcha da NF-e e do CT-e e o código de imagem da NFC-e de SP. A tela da nota é inventada (a real só aparece depois de uma pessoa resolver o captcha), em três
estruturas de HTML diferentes para provar que a leitura por rótulos não depende de uma só. O servidor só mostra a nota se
o token do captcha vier preenchido."""

from __future__ import annotations

import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List
from urllib.parse import parse_qs

CAMPO = "ctl00_ContentPlaceHolder1_txtChaveAcessoResumo"
BOTAO = "ctl00_ContentPlaceHolder1_btnConsultarHCaptcha"

FORMULARIO = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Portal da NF-e (falso)</title></head><body>
<h1>Consulta Resumo da NF-e</h1>{erro}
<form id="aspnetForm" action="/consulta" method="post">
  <label for="{campo}">Chave de Acesso</label>
  <input type="text" id="{campo}" name="ctl00$ContentPlaceHolder1$txtChaveAcessoResumo" maxlength="44">
  <div class="h-captcha" data-sitekey="mock">
    <iframe title="Widget contendo caixa de selecao para desafio de seguranca hCaptcha" src="/hcaptcha-falso" width="300" height="80"></iframe>
    <textarea name="h-captcha-response" style="display:none">{token}</textarea>
    <button id="humano-ok" type="button" onclick="document.querySelector('[name=h-captcha-response]').value='token-do-captcha-resolvido-0123456789'">Resolvi o captcha</button>
  </div>
  <input type="submit" id="{botao}" name="ctl00$ContentPlaceHolder1$btnConsultarHCaptcha" value="Continuar">
</form></body></html>"""

NOTA_LABEL = """<!doctype html><html><body><h1>Resultado da consulta</h1>
<fieldset><legend>Dados da NF-e</legend><table><tr>
 <td><label>Chave de acesso</label><span>{chave_fmt}</span></td><td><label>Número</label><span>{numero}</span></td>
 <td><label>Série</label><span>1</span></td><td><label>Modelo</label><span>55</span></td>
 <td><label>Data de Emissão</label><span>15/09/2026</span></td><td><label>Valor Total da NF-e</label><span>R$ 1.234,56</span></td>
</tr></table></fieldset>
<fieldset><legend>Emitente</legend><table><tr>
 <td><label>CNPJ</label><span>11.222.333/0001-81</span></td><td><label>Nome/Razão Social</label><span>COMERCIO DE TESTE LTDA</span></td>
 <td><label>UF</label><span>SP</span></td></tr></table></fieldset>
<fieldset><legend>Destinatário</legend><table><tr>
 <td><label>CPF</label><span>529.982.247-25</span></td><td><label>Nome</label><span>FULANO DE TAL</span></td><td><label>UF</label><span>MG</span></td>
</tr></table></fieldset>
<fieldset><legend>Situação Atual</legend><table><tr><td><label>Situação</label><span>AUTORIZADA</span></td><td><label>Protocolo</label><span>135260000012345</span></td></tr></table></fieldset>
</body></html>"""

NOTA_TABELA = """<!doctype html><html><body><h2>Dados da NF-e</h2>
<table><tr><th>Chave de acesso</th><td>{chave_fmt}</td></tr><tr><th>Número</th><td>{numero}</td></tr><tr><th>Valor Total da NF-e</th><td>987,65</td></tr>
<tr><th>Situação</th><td>CANCELADA</td></tr></table>
<h2>Emitente</h2><table><tr><th>CNPJ</th><td>11.222.333/0001-81</td></tr><tr><th>Razão Social</th><td>OUTRA EMPRESA SA</td></tr></table>
</body></html>"""

NOTA_LINHAS = """<!doctype html><html><body><h2>Dados da NF-e</h2>
<p>Número: {numero}</p><p>Valor Total: 50,00</p><p>Situação: AUTORIZADA</p></body></html>"""

NOTA_SEM_ROTULOS = """<!doctype html><html><body><h2>Dados da NF-e</h2><div>conteudo sem nenhum rotulo reconhecivel</div></body></html>"""

CTE = """<!doctype html><html><body><fieldset><legend>Dados do CT-e</legend>
<label>Chave de acesso</label><span>{chave_fmt}</span><label>Número</label><span>{numero}</span>
<label>Valor Total da Prestação do Serviço</label><span>350,00</span></fieldset>
<fieldset><legend>Emitente</legend><label>Nome/Razão Social</label><span>TRANSPORTES TESTE LTDA</span></fieldset>
<fieldset><legend>Tomador do Serviço</legend><label>CNPJ</label><span>11.222.333/0001-81</span></fieldset>
<fieldset><legend>Situação Atual</legend><label>Situação</label><span>AUTORIZADO</span></fieldset></body></html>"""

FORMULARIO_NFCE_SP = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Consulta NFC-e (falsa)</title></head><body>
<h1>Consulta Pública NFC-e</h1>{erro}
<form method="post" action="/consulta">
  <label for="Conteudo_txtChaveAcesso">Chave de Acesso</label>
  <input type="text" id="Conteudo_txtChaveAcesso" name="ctl00$Conteudo$txtChaveAcesso">
  <img id="imgCaptcha" alt="código" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">
  <input type="text" id="txCodigo" name="txCodigo">
  <input type="submit" id="Conteudo_btnConsultaResumida" name="ctl00$Conteudo$btnConsultaResumida" value="Consultar">
</form></body></html>"""

NFCE = """<!doctype html><html><body><h2>Dados da NFC-e</h2>
<table><tr><th>Número</th><td>{numero}</td></tr><tr><th>Valor total</th><td>R$ 42,90</td></tr><tr><th>Situação</th><td>AUTORIZADA</td></tr></table>
<h2>Dados do Emitente</h2><table><tr><th>Razão Social</th><td>MERCADO TESTE LTDA</td></tr></table></body></html>"""

CODIGO_DA_IMAGEM = "AB12C"

ESTRUTURAS = {"label": NOTA_LABEL, "tabela": NOTA_TABELA, "linhas": NOTA_LINHAS, "sem_rotulos": NOTA_SEM_ROTULOS, "cte": CTE}


def chave_com_dv(base43: str) -> str:
    """Completa os 43 primeiros dígitos com o dígito verificador (módulo 11), como faz quem emite a nota."""
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    resto = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(base43))) % 11
    return base43 + str(0 if resto in (0, 1) else 11 - resto)


def formatar_chave(chave: str) -> str:
    return " ".join(chave[i:i + 4] for i in range(0, 44, 4))


class NfeFalsa:
    def __init__(self, estrutura: str = "label", notas_existentes: tuple = (), pre_resolvido: bool = False, rejeitar_primeiro_token: bool = False,
                 bloquear: bool = False, nfce_sp: bool = False):
        self.estrutura, self.notas, self.pre_resolvido = estrutura, set(notas_existentes), pre_resolvido
        self.nfce_sp = nfce_sp  # a tela da NFC-e de SP: código de imagem em vez do hCaptcha
        self.rejeitar_primeiro_token, self.bloquear = rejeitar_primeiro_token, bloquear
        self.envios: List[Dict[str, str]] = []
        portal = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _enviar(self, corpo: str, status: int = 200):
                dados = corpo.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def do_GET(self):
                if self.path.startswith("/hcaptcha-falso"):
                    return self._enviar("<!doctype html><html><body>[ ] Sou humano</body></html>")
                self._enviar(portal.formulario())

            def do_POST(self):
                campos = parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
                envio = {k: v[0] for k, v in campos.items()}
                portal.envios.append(envio)
                if portal.bloquear:
                    return self._enviar("<html><body>Acesso negado: comportamento de robô detectado.</body></html>")
                if portal.nfce_sp:
                    if envio.get("txCodigo", "") != CODIGO_DA_IMAGEM:
                        return self._enviar(portal.formulario(erro="<p class='erro'>Código da imagem incorreto.</p>"))
                    chave = "".join(c for c in envio.get("ctl00$Conteudo$txtChaveAcesso", "") if c.isdigit())
                    return self._enviar(NFCE.format(numero=str(int(chave[25:34]))))
                token = envio.get("h-captcha-response", "")
                if not token or (portal.rejeitar_primeiro_token and len(portal.envios) == 1):
                    return self._enviar(portal.formulario(erro='<p class="erro">Resolva o desafio do captcha.</p>'))
                chave = "".join(c for c in envio.get("ctl00$ContentPlaceHolder1$txtChaveAcessoResumo", "") if c.isdigit())
                if portal.notas and chave not in portal.notas:
                    return self._enviar(portal.formulario(erro="<p class='erro'>NF-e não encontrada para a chave informada.</p>"))
                self._enviar(ESTRUTURAS[portal.estrutura].format(chave_fmt=formatar_chave(chave), numero=str(int(chave[25:34]))))

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def formulario(self, erro: str = "") -> str:
        if self.nfce_sp:
            return FORMULARIO_NFCE_SP.format(erro=erro)
        token = "token-do-captcha-resolvido-0123456789" if self.pre_resolvido else ""
        return FORMULARIO.format(erro=erro, campo=CAMPO, botao=BOTAO, token=escape(token))

    def parar(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
