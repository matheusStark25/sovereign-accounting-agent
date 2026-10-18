"""Gravador de calibragem do portal do FGTS.

O robô precisa de seletores que só existem no portal de verdade, e o portal exige login e captcha. Este gravador
resolve isso sem adivinhar: abre um navegador de verdade, **uma pessoa** faz o caminho normal (login, menus, extrato,
download) e o gravador registra só a *estrutura* do que ela tocou: hosts, caminhos, botões, campos e links (com
seletores sugeridos) e downloads. Com isso se escreve o fluxo do robô com base no portal real.

Privacidade, por construção:
* nada do que é digitado é gravado (não há ouvinte de teclado nem leitura de ``value``);
* números com 4+ dígitos e e-mails viram ``####`` e ``***@***`` nos textos; textos são cortados em 60 caracteres;
* o PDF baixado fica só na pasta de saída (permissão 0600) e entra no relatório apenas como tamanho e SHA-256;
* nenhum captcha é resolvido e nada é escondido: é o navegador normal, guiado por uma pessoa.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

JS_ESTRUTURA = r"""
(() => {
  if (window.__estruturaAtiva) return;
  window.__estruturaAtiva = true;
  const mascara = (s) => String(s || '').replace(/\s+/g, ' ').trim()
    .replace(/\d{4,}/g, '####').replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '***@***').slice(0, 60);
  const visivel = (el) => !!(el.offsetParent || (el.getClientRects && el.getClientRects().length));
  const unico = (css) => { try { return document.querySelectorAll(css).length === 1; } catch (e) { return false; } };
  const descreve = (el) => {
    const tag = el.tagName.toLowerCase();
    const tipo = (el.getAttribute('type') || '').toLowerCase();
    const campo = tag === 'input' || tag === 'textarea' || tag === 'select';
    let rotulo = '';
    if (campo) {
      const lab = el.labels && el.labels[0] ? el.labels[0].innerText : '';
      rotulo = mascara(el.getAttribute('aria-label') || lab || el.getAttribute('placeholder') || '');
    } else {
      rotulo = mascara(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '');
    }
    const id = el.id || null, nome = el.getAttribute('name'), aria = el.getAttribute('aria-label');
    const sugestoes = [];
    if (id && unico('#' + CSS.escape(id))) sugestoes.push('#' + id);
    if (nome && unico(tag + '[name="' + nome + '"]')) sugestoes.push(tag + "[name='" + nome + "']");
    if (aria) sugestoes.push(tag + "[aria-label='" + aria.replace(/'/g, '') + "']");
    if (campo && el.getAttribute('placeholder')) sugestoes.push(tag + "[placeholder*='" + el.getAttribute('placeholder').replace(/'/g, '').slice(0, 30) + "']");
    if (!campo && rotulo && rotulo.length <= 40 && !rotulo.includes('#')) sugestoes.push(tag + ":has-text('" + rotulo.replace(/'/g, '') + "')");
    if (campo && tipo) sugestoes.push(tag + "[type='" + tipo + "']");
    let href = null;
    if (el.href) { try { const u = new URL(el.href); href = u.host + u.pathname; } catch (e) {} }
    return {
      tag, tipo: tipo || null, id, nome, papel: el.getAttribute('role'), rotulo, href,
      classes: (el.className && el.className.toString ? el.className.toString().split(/\s+/).filter(Boolean).slice(0, 4).join(' ') : ''),
      dentro_de_form: !!el.closest('form'), sugestoes: sugestoes.slice(0, 5),
    };
  };
  window.__instantaneo = () => Array.from(document.querySelectorAll(
    'input,button,a[href],select,textarea,[role=button],[role=link],[role=menuitem],[role=tab]'))
    .filter(visivel).slice(0, 150).map(descreve);
  window.__descreve = descreve;
})();
"""

SCRIPT = JS_ESTRUTURA + r"""
(() => {
  if (window.__calibragemAtiva) return;
  window.__calibragemAtiva = true;
  document.addEventListener('click', (e) => {
    const alvo = e.target.closest ? e.target.closest('a,button,input,select,textarea,label,[role=button],[role=link],[role=menuitem],[role=tab],[onclick]') : null;
    const el = alvo || e.target;
    if (el && el.nodeType === 1) window.__registrar({ evento: 'clique', ...window.__descreve(el) });
  }, true);
})();
"""


def _web(url: str) -> bool:
    """Só páginas http(s): about:blank, edge://downloads-hub etc. são do navegador, não do portal."""
    return urlparse(url or "").scheme in ("http", "https")


def _local(url: str) -> Dict[str, str]:
    u = urlparse(url or "")
    return {"host": u.hostname or "", "caminho": u.path or "/"}  # sem query nem fragmento: podem trazer dados pessoais


def calibrar(
    url: str,
    saida: str | Path,
    canal: Optional[str] = None,
    user_data_dir: Optional[str] = None,
    headless: bool = False,
    humano: Optional[Callable[[Any], None]] = None,
    tempo_maximo_s: int = 1800,
) -> Dict[str, Any]:
    """Abre o portal e grava a estrutura do caminho feito por uma pessoa. Termina quando todas as janelas fecham
    (ou, nos testes, quando ``humano(contexto)`` retorna). Devolve o relatório, também salvo em ``calibragem.json``."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    pasta = Path(saida)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "downloads").mkdir(exist_ok=True)
    arquivo = pasta / "calibragem.json"
    eventos: List[Dict[str, Any]] = []
    pendentes: List[tuple] = []  # (quando, pagina): instantâneos da estrutura a tirar
    vistos: set = set()
    inicio = time.time()

    def gravar(evento: Dict[str, Any]) -> None:
        eventos.append({"t": round(time.time() - inicio, 2), **evento})
        arquivo.write_text(json.dumps(relatorio(), ensure_ascii=False, indent=1), encoding="utf-8")

    def relatorio() -> Dict[str, Any]:
        hosts = sorted({e["host"] for e in eventos if e.get("host")})
        return {
            "url_inicial": url, "hosts": hosts,
            "downloads": [e for e in eventos if e["evento"] == "download"],
            "cliques": sum(1 for e in eventos if e["evento"] == "clique"),
            "eventos": eventos,
        }

    def registrar(origem, dados) -> None:  # chamado pelo JavaScript da página a cada clique
        pagina = origem["page"]
        if not _web(pagina.url):
            return
        gravar({**dados, **_local(pagina.url)})
        pendentes.append((time.time() + 1.5, pagina))

    def ao_baixar(download) -> None:
        nome = (download.suggested_filename or "arquivo").replace("\\", "_").replace("/", "_")
        temporario = pasta / "downloads" / f"baixando_{int(time.time() * 1000)}.tmp"
        download.save_as(str(temporario))
        dados = temporario.read_bytes()
        sha = hashlib.sha256(dados).hexdigest()
        destino = pasta / "downloads" / f"{sha[:16]}{os.path.splitext(nome)[1].lower()[:8]}"
        os.replace(temporario, destino)
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
        gravar({"evento": "download", **_local(download.url), "nome_sugerido_extensao": os.path.splitext(nome)[1].lower(),
                "e_pdf": dados[:5] == b"%PDF-", "tamanho": len(dados), "sha256": sha, "arquivo_local": str(destino)})

    def observar(pagina) -> None:
        def ao_navegar(frame) -> None:
            if frame == pagina.main_frame and _web(frame.url):
                gravar({"evento": "navegou", **_local(frame.url)})
                pendentes.append((time.time() + 1.5, pagina))

        pagina.on("download", ao_baixar)
        pagina.on("framenavigated", ao_navegar)

    def instantaneo(pagina) -> None:
        try:
            elementos = pagina.evaluate("window.__instantaneo ? window.__instantaneo() : []") if _web(pagina.url) else []
        except PlaywrightError:
            return  # a página mudou ou fechou durante a leitura
        assinatura = hashlib.sha1(json.dumps([_local(pagina.url), elementos], sort_keys=True).encode()).hexdigest()
        if elementos and assinatura not in vistos:
            vistos.add(assinatura)
            gravar({"evento": "elementos", **_local(pagina.url), "quantidade": len(elementos), "elementos": elementos})

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir or str(pasta / "perfil"), headless=headless, channel=canal, accept_downloads=True,
            viewport={"width": 1366, "height": 900},
        )
        try:
            contexto.expose_binding("__registrar", registrar)
            contexto.add_init_script(SCRIPT)
            contexto.on("page", observar)
            pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
            observar(pagina)
            pagina.goto(url, wait_until="domcontentloaded")

            def bombear(segundos: float) -> bool:
                """Deixa a pessoa agir: processa os eventos do navegador e tira os instantâneos pendentes.
                Devolve ``False`` quando todas as janelas foram fechadas."""
                fim = time.time() + segundos
                while time.time() < fim:
                    try:
                        abertas = [pg for pg in contexto.pages if not pg.is_closed()]
                        if not abertas:
                            return False
                        abertas[0].wait_for_timeout(500)
                    except PlaywrightError:
                        return False  # a pessoa fechou o navegador
                    agora = time.time()
                    prontos = [pg for quando, pg in pendentes if quando <= agora]
                    pendentes[:] = [(q, pg) for q, pg in pendentes if q > agora]
                    for pg in prontos:
                        instantaneo(pg)
                return True

            if humano is not None:
                humano(contexto, bombear)  # nos testes: um roteiro que faz o papel da pessoa e usa ``bombear`` como pausa
                bombear(2.5)
            else:
                bombear(tempo_maximo_s)
            for quando, pg in list(pendentes):
                instantaneo(pg)
        finally:
            try:
                contexto.close()
            except PlaywrightError:
                pass
    resultado = relatorio()
    arquivo.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(arquivo, 0o600)
    except OSError:
        pass
    return resultado
