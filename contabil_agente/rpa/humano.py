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


class PortaDoHumano:
    def __init__(
        self,
        seletores: Sequence[str],
        timeout_s: int = 300,
        notificar: Optional[Callable[[str, str, object], None]] = None,
        intervalo_s: float = 1.0,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self.seletores, self.timeout_s, self.intervalo_s = tuple(seletores), timeout_s, intervalo_s
        self._notificar, self._relogio = notificar, relogio

    def esperar(self, page, motivo: str) -> float:
        """Bloqueia até o desafio sumir. Devolve quantos segundos a pessoa levou; levanta ``HumanoNaoRespondeu``."""
        inicio = self._relogio()
        seletor = desafio_visivel(page, self.seletores)
        if seletor is None:
            return 0.0
        if self._notificar is not None:
            self._notificar(motivo, seletor, page)
        while True:
            if desafio_visivel(page, self.seletores) is None:
                return self._relogio() - inicio
            if self._relogio() - inicio > self.timeout_s:
                raise HumanoNaoRespondeu(f"Ninguém resolveu o desafio ({motivo}) em {self.timeout_s}s.")
            page.wait_for_timeout(int(self.intervalo_s * 1000))
