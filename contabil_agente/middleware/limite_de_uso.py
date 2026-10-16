"""Limite de uso por janela deslizante, em memória (por processo).

Com vários workers cada processo tem o seu contador: para um limite global use também o proxy/WAF
(veja ``nginx/nginx.conf``). Serve contra força bruta e abuso simples.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict


class LimiteDeUso:
    def __init__(self, maximo: int, janela_segundos: int, relogio: Callable[[], float] = time.monotonic):
        if maximo < 1 or janela_segundos < 1:
            raise ValueError("maximo e janela_segundos devem ser >= 1.")
        self.maximo, self.janela, self._relogio = maximo, janela_segundos, relogio
        self._eventos: Dict[str, Deque[float]] = defaultdict(deque)

    def permitir(self, chave: str) -> bool:
        agora = self._relogio()
        fila = self._eventos[chave]
        while fila and agora - fila[0] > self.janela:
            fila.popleft()
        if len(fila) >= self.maximo:
            return False
        fila.append(agora)
        if not fila and chave in self._eventos:
            del self._eventos[chave]
        return True
