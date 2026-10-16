"""Regra de evidência: um valor só entra no resultado se aparece no texto do documento.

É a defesa contra alucinação do LLM: o modelo pode *sugerir* um valor, mas o sistema só o aceita se
conseguir encontrá-lo no documento (em qualquer formato razoável: 6000.00 -> 6.000,00).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, List


def _so_digitos(t: str) -> str:
    return re.sub(r"\D", "", t)


def variantes(valor: Any) -> List[str]:
    """Formas em que ``valor`` poderia aparecer escrito no documento."""
    if valor is None:
        return []
    texto = str(valor).strip()
    if not texto:
        return []
    saida = {texto}
    try:
        d = Decimal(texto)
    except InvalidOperation:
        d = None
    if d is not None and "." in texto:
        inteiro, _, dec = f"{d:.2f}".partition(".")
        saida.add(f"{inteiro},{dec}")
        saida.add(f"{int(inteiro):,}".replace(",", ".") + f",{dec}")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        a, m, dia = texto.split("-")
        saida.update({f"{dia}/{m}/{a}", f"{dia}-{m}-{a}", f"{dia}{m}{a}"})
    if re.fullmatch(r"\d{4}-\d{2}", texto):
        a, m = texto.split("-")
        saida.update({f"{m}/{a}", f"{int(m)}/{a}", f"{m}-{a}"})
    return list(saida)


def valor_aparece(texto: str, valor: Any) -> bool:
    if valor is None or str(valor).strip() == "":
        return False
    base = texto.lower()
    for v in variantes(valor):
        if v.lower() in base:
            return True
    digitos = _so_digitos(str(valor))
    if len(digitos) >= 11:  # CPF/CNPJ/chaves: compara sem pontuação
        return digitos in _so_digitos(texto)
    return False
