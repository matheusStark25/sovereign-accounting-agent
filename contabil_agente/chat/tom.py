"""Tom adaptativo: o MARCOS responde no jeito de quem escreve (ou fala): ``formal``, ``informal`` ou ``base`` (neutro).

Olha as últimas mensagens da pessoa e conta marcas claras de cada tom (tratamento "senhor/senhora", "gostaria", "prezado"
contra "vc", "pq", "blz", gírias, xingamento, GRITO em maiúsculas). Empate ou nenhuma marca: ``base``. Não adivinha: sem
marca clara, fica no tom neutro.
"""

from __future__ import annotations

import re
from typing import Iterable

FORMAL = (
    r"prezad[oa]s?", r"senhor(?:a|es|as)?", r"gostaria", r"poderia(?:m)?", r"solicito", r"por gentileza", r"cordialmente",
    r"atenciosamente", r"venho por meio", r"agradeco", r"agradeço", r"estimad[oa]s?", r"vossa", r"vossa senhoria",
)
INFORMAL = (
    r"vc", r"vcs", r"pq", r"blz", r"tb", r"tbm", r"msm", r"dnv", r"mano", r"cara", r"valeu", r"falou", r"opa", r"bora", r"tô", r"to",
    r"tá", r"né", r"ne", r"kkk+", r"kk+", r"rsrs", r"haha+", r"eae", r"e aí", r"fala", r"firmeza", r"top", r"massa", r"daora",
    r"porra", r"caramba", r"caralho", r"droga", r"merda", r"puta", r"pra", r"pro",
)
_RX_FORMAL = re.compile(r"\b(?:" + "|".join(FORMAL) + r")\b", re.IGNORECASE)
# "to" e "ne" sozinhos são ambíguos ("to" aparece em inglês e "ne" em siglas): só contam fora de números/siglas
_RX_INFORMAL = re.compile(r"(?<![\w/.-])(?:" + "|".join(INFORMAL) + r")(?![\w/.-])", re.IGNORECASE)


def _pontos(texto: str) -> int:
    """Positivo = informal, negativo = formal, zero = sem marca clara."""
    informais = len(_RX_INFORMAL.findall(texto))
    formais = len(_RX_FORMAL.findall(texto))
    letras = [c for c in texto if c.isalpha()]
    if len(letras) >= 10 and sum(c.isupper() for c in letras) / len(letras) > 0.8:
        informais += 1  # escrito em MAIÚSCULAS: gritando
    if texto.count("!") >= 3:
        informais += 1
    return informais - formais


def escolher_variante(mensagens_do_usuario: Iterable[str], janela: int = 3) -> str:
    """``"formal"``, ``"informal"`` ou ``"base"`` pelas últimas ``janela`` mensagens (a mais recente pesa mais)."""
    recentes = [m for m in list(mensagens_do_usuario)[-janela:] if m]
    total = 0
    for peso, texto in enumerate(recentes, 1):  # a última mensagem tem o maior peso
        total += _pontos(texto) * peso
    return "informal" if total > 0 else "formal" if total < 0 else "base"
