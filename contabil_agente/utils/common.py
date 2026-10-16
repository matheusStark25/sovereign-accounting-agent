"""Common utilities extracted from agent_contabil.py

Functions moved here to avoid a single very large module while keeping
backwards-compatible imports via contabil_agente.utils.
"""

from __future__ import annotations

import re
from decimal import Decimal


def parse_brl_to_float(texto: str) -> tuple[bool, float | str]:
    """Parse BRL textual representations deterministically.

    Returns (True, float) on success or (False, error_message) on failure.
    Supports formats like:
      - 'R$ 1.500,50'
      - '1500,50'
      - '1.500.000,75'
      - simple written Portuguese numbers like 'mil e quinhentos' (basic support)
    Does NOT call an LLM; returns error immediately on ambiguous input.
    """
    if not texto or not isinstance(texto, str):
        return False, "valor vazio ou tipo inválido"
    s = texto.strip().lower()
    # remove currency symbol
    s = s.replace("r$", "").strip()

    # pattern for numbers like 1.234,56 or 1234,56 or 1234.56
    m = re.search(r"[\d\.\,]+", s)
    if m:
        num = m.group(0)
        # handle cases like '3 mil' where the numeric token is followed by 'mil'
        try:
            post = s[m.end() :]
            if re.search(r"^\s*mil\b", post):
                try:
                    val = float(num) * 1000
                    return True, val
                except Exception:
                    pass
        except Exception:
            pass
        # if contains ',' as decimal separator and '.' as thousands
        if num.count(",") == 1 and num.count(".") >= 1:
            num = num.replace(".", "")
            num = num.replace(",", ".")
        elif num.count(",") == 1 and num.count(".") == 0:
            num = num.replace(",", ".")
        else:
            # maybe already dot-decimal
            num = num.replace(",", ".")
        try:
            val = float(num)
            return True, val
        except Exception:
            pass

    # basic Portuguese words -> number mapping (limited coverage)
    words_map = {
        "mil": 1000,
        "cem": 100,
        "duzentos": 200,
        "trezentos": 300,
        "quatrocentos": 400,
        "quinhentos": 500,
        "seiscentos": 600,
        "setecentos": 700,
        "oitocentos": 800,
        "novecentos": 900,
        "cinquenta": 50,
        "vinte": 20,
        "dez": 10,
        "cinco": 5,
        "tres": 3,
        "dois": 2,
        "um": 1,
    }
    parts = re.split(r"[\s\-e]+", s)
    total = 0
    found = False
    i = 0
    while i < len(parts):
        p = parts[i]
        # numeric token followed by 'mil' -> multiplier
        if p.isdigit():
            num = int(p)
            if i + 1 < len(parts) and parts[i + 1] == "mil":
                total += num * 1000
                found = True
                i += 2
                continue
            else:
                total += num
                found = True
                i += 1
                continue

        # word-number mapping
        if p in words_map:
            # if next token is 'mil', multiply
            if i + 1 < len(parts) and parts[i + 1] == "mil":
                total += words_map[p] * 1000
                found = True
                i += 2
                continue
            total += words_map[p]
            found = True
            i += 1
            continue

        i += 1

    if found:
        return True, float(total)

    return False, "valor não reconhecido como numérico"


def format_brl(valor: float) -> str:
    """Format a float as BRL 'R$ 1.234,56' deterministically (no locale reliance)."""
    try:
        v = float(valor)
    except Exception:
        return "R$ 0,00"
    # separate integer and decimals
    inteiro = int(abs(int(v)))
    dec = abs(v) - inteiro
    cents = int(round(dec * 100))
    # format thousands with '.'
    s_int = f"{inteiro:,}".replace(",", ".")
    sign = "-" if v < 0 else ""
    return f"{sign}R$ {s_int},{cents:02d}"


def _is_approximate_text(texto: str) -> bool:
    """Detect simple Portuguese cues that indicate an approximate value."""
    if not texto or not isinstance(texto, str):
        return False
    s = texto.lower()
    # detect common qualifiers or 'k' suffixes like '5k' or '3k'
    if re.search(r"\b(uns|aprox(?:imad)?|por volta|mais ou menos|~|cerca)\b", s):
        return True
    if re.search(r"\d+[kK]\b", s):
        return True
    return False


def _normalize_k_suffix(texto: str) -> str:
    """Convert simple '5k' style tokens into full digits (5000).

    This is a best-effort, deterministic normalization used before numeric parsing.
    """
    if not texto or not isinstance(texto, str):
        return texto

    def _repl(m):
        try:
            v = float(m.group(1).replace(",", "."))
            return str(int(v * 1000))
        except Exception:
            return m.group(0)

    return re.sub(r"(\d+(?:[.,]\d+)?)[kK]\b", _repl, texto)


def safe_decimal(value, default=Decimal("0")) -> Decimal:
    """Converte de forma segura valores para Decimal.

    - Retorna `default` quando `value` é None ou string vazia.
    - Trata ints/floats/Decimals e strings com separadores comuns.
    - Nunca levanta InvalidOperation para entradas triviais; retorna `default`.
    """
    from decimal import Decimal as _D
    import re as _re

    if value is None:
        return default
    if isinstance(value, _D):
        return value
    if isinstance(value, bool):
        return default
    try:
        if isinstance(value, (int, float)):
            return _D(str(value))
        if isinstance(value, str):
            s = value.strip()
            if s == "":
                return default
            # normalize common thousand/decimal separators (e.g. 1.234,56)
            if _re.match(r"^[\d\.,]+$", s):
                # if both . and , present, assume . thousands and , decimal
                if s.count(",") == 1 and s.count(".") >= 1:
                    s = s.replace(".", "").replace(",", ".")
                else:
                    s = s.replace(",", ".")
            return _D(s)
        # fallback: try str()
        return _D(str(value))
    except Exception:
        try:
            return _D(str(default))
        except Exception:
            return default


def _is_small_talk(texto: str) -> bool:
    """Simple small-talk detector to redirect out-of-scope chit-chat.

    This is intentionally conservative and only detects obvious non-contábil intents like weather.
    """
    if not texto or not isinstance(texto, str):
        return False

    s = texto.lower()
    # detect weather / time / small talk keywords
    for kw in ("tempo", "clima", "hoje", "amanhã", "tudo bem", "oi", "olá", "bom dia"):
        if kw in s:
            return True

        return False
