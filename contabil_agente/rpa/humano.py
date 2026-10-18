"""Pausa para a pessoa resolver captcha ou login (human-in-the-loop). O robô nunca resolve captcha.

Quando um desafio aparece, o robô chama ``notificar(motivo, seletor, page)`` (por exemplo, para avisar o operador pela API) e
fica verificando a página até o desafio sumir ou o tempo acabar. Nada aqui tenta resolver, contornar ou
esconder o desafio: sem a pessoa, a tarefa termina com ``HumanoNaoRespondeu``.
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Sequence


class RequerAcaoHumana(Exception):
    """O portal pediu algo que só uma pessoa pode fazer."""


class HumanoNaoRespondeu(RequerAcaoHumana):
    """Ninguém resolveu o desafio dentro do prazo."""


def desafio_visivel(page, seletores: Sequence[str]) -> Optional[str]:
    """Primeiro seletor de desafio (captcha/login) presente e visível na página, ou ``None``."""
    for seletor in seletores:
        try:
            loc = page.locator(seletor)
            if loc.count() > 0 and loc.first.is_visible():
                return seletor
        except Exception:  # noqa: BLE001 - página navegando; tenta de novo no próximo ciclo
            continue
    return None


_JS_HCAPTCHA_RESOLVIDO = """() => {
  const campos = document.querySelectorAll("textarea[name='h-captcha-response'], textarea[id^='h-captcha-response']");
  if ([...campos].some(c => (c.value || '').length > 10)) return true;
  return [...document.querySelectorAll('iframe[data-hcaptcha-response]')].some(f => (f.getAttribute('data-hcaptcha-response') || '').length > 10);
}"""


def hcaptcha_resolvido(page) -> bool:
    """O hCaptcha continua na tela depois de resolvido; o sinal de que a pessoa terminou é o token de resposta preenchido."""
    try:
        return bool(page.evaluate(_JS_HCAPTCHA_RESOLVIDO))
    except Exception:  # noqa: BLE001 - página navegando; tenta de novo no próximo ciclo
        return False


_JS_AJUDA = r"""(texto) => {
  let caixa = document.getElementById('__robo_ajuda');
  if (!caixa) {
    caixa = document.createElement('div');
    caixa.id = '__robo_ajuda';
    caixa.style.cssText = 'position:fixed;z-index:2147483647;left:0;right:0;top:0;padding:10px 14px;background:#fff3cd;color:#222;' +
      'font:14px sans-serif;border-bottom:2px solid #e0a800;display:flex;gap:12px;align-items:center';
    const t = document.createElement('span');
    t.id = '__robo_ajuda_texto';
    caixa.appendChild(t);
    const b = document.createElement('button');
    b.id = '__robo_terminei';
    b.type = 'button';
    b.textContent = 'Terminei esta etapa';
    b.onclick = () => { window.__roboTerminei = true; };
    caixa.appendChild(b);
    document.documentElement.appendChild(caixa);
  }
  document.getElementById('__robo_ajuda_texto').textContent = texto;
  return !!window.__roboTerminei;
}"""


class PortaDoHumano:
    def __init__(
        self,
        seletores: Sequence[str],
        timeout_s: int = 300,
        notificar: Optional[Callable[[str, str, object], None]] = None,
        intervalo_s: float = 1.0,
        relogio: Callable[[], float] = time.monotonic,
        resolvido: Optional[Callable[[object], bool]] = None,
    ):
        """``resolvido(page)``: para desafios que ficam visíveis depois de resolvidos (hCaptcha), diz quando a pessoa terminou."""
        self.seletores, self.timeout_s, self.intervalo_s = tuple(seletores), timeout_s, intervalo_s
        self._notificar, self._relogio, self._resolvido = notificar, relogio, resolvido

    def assistir(self, page, etapa: str, instrucao: str, concluido: Optional[Callable[[], bool]] = None) -> float:
        """O robô não achou algo: em vez de abortar, mostra um aviso na própria página e espera a pessoa fazer a etapa.

        A pessoa clica em "Terminei esta etapa" (ou, se ``concluido()`` ficar verdadeiro, como um download que ela mesma
        iniciou, o robô segue sozinho). Devolve os segundos esperados; levanta ``HumanoNaoRespondeu`` se estourar o prazo."""
        inicio = self._relogio()
        if self._notificar is not None:
            self._notificar(f"{etapa}: {instrucao}", "assistencia", page)
        while True:
            terminou = False
            try:
                terminou = bool(page.evaluate(_JS_AJUDA, instrucao))  # recoloca o aviso se a página mudou
            except Exception:  # noqa: BLE001 - página navegando; tenta de novo no próximo ciclo
                pass
            if terminou or (concluido is not None and concluido()):
                try:
                    page.evaluate("() => { const c = document.getElementById('__robo_ajuda'); if (c) c.remove(); window.__roboTerminei = false; }")
                except Exception:  # noqa: BLE001
                    pass
                return self._relogio() - inicio
            if self._relogio() - inicio > self.timeout_s:
                raise HumanoNaoRespondeu(f"Ninguém fez a etapa ({etapa}) em {self.timeout_s}s.")
            page.wait_for_timeout(int(self.intervalo_s * 1000))

    def esperar(self, page, motivo: str) -> float:
        """Bloqueia até o desafio sumir. Devolve quantos segundos a pessoa levou; levanta ``HumanoNaoRespondeu``."""
        inicio = self._relogio()
        seletor = desafio_visivel(page, self.seletores)
        if seletor is None or (self._resolvido is not None and self._resolvido(page)):
            return 0.0
        if self._notificar is not None:
            self._notificar(motivo, seletor, page)
        while True:
            if desafio_visivel(page, self.seletores) is None or (self._resolvido is not None and self._resolvido(page)):
                return self._relogio() - inicio
            if self._relogio() - inicio > self.timeout_s:
                raise HumanoNaoRespondeu(f"Ninguém resolveu o desafio ({motivo}) em {self.timeout_s}s.")
            page.wait_for_timeout(int(self.intervalo_s * 1000))
