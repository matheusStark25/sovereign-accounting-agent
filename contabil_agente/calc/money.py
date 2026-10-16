"""Aritmética monetária com Decimal (nunca float)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from .errors import DadosInvalidos

CENT = Decimal("0.01")
ZERO = Decimal("0")


def D(valor: Any, campo: str = "valor") -> Decimal:
    """Converte para Decimal sem ruído binário e recusa NaN/infinito.

    Aceita Decimal, int, str ("1234.56") e float (via str).
    Strings no formato brasileiro ("1.234,56" ou "R$ 1.234,56") também são aceitas.
    """
    if isinstance(valor, bool) or valor is None:
        raise DadosInvalidos(f"{campo}: valor ausente ou inválido ({valor!r})")
    if isinstance(valor, Decimal):
        d = valor
    elif isinstance(valor, (int, float)):
        d = Decimal(str(valor))
    elif isinstance(valor, str):
        s = valor.strip().replace("R$", "").replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            d = Decimal(s)
        except InvalidOperation as exc:
            raise DadosInvalidos(f"{campo}: não consegui ler {valor!r} como número") from exc
    else:
        raise DadosInvalidos(f"{campo}: tipo não suportado ({type(valor).__name__})")
    if not d.is_finite():
        raise DadosInvalidos(f"{campo}: número inválido ({valor!r})")
    return d


def q2(valor: Decimal) -> Decimal:
    """Arredonda para centavos, metade para cima (padrão da folha)."""
    return valor.quantize(CENT, rounding=ROUND_HALF_UP)


def nao_negativo(valor: Decimal, campo: str) -> Decimal:
    if valor < 0:
        raise DadosInvalidos(f"{campo}: não pode ser negativo ({valor})")
    return valor
