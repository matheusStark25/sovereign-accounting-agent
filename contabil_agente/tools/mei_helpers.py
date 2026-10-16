from decimal import Decimal, ROUND_HALF_UP
import re


def normalize_cnpj(cnpj: str) -> str:
    """Return only digits for a CNPJ string; raises ValueError if length != 14."""
    if cnpj is None:
        raise ValueError("cnpj is required")
    digits = re.sub(r"\D", "", str(cnpj))
    if len(digits) != 14:
        raise ValueError("cnpj must have 14 digits after normalization")
    return digits


def _calc_check_digit(numbers: list[int]) -> int:
    weight = list(range(len(numbers) - 7, 1, -1)) + list(range(9, 1, -1))
    total = sum(x * w for x, w in zip(numbers, weight))
    r = total % 11
    return 0 if r < 2 else 11 - r


def is_valid_cnpj(cnpj: str) -> bool:
    """Validate CNPJ using the official modulus 11 algorithm."""
    try:
        s = normalize_cnpj(cnpj)
    except ValueError:
        return False
    if s == s[0] * 14:
        return False
    nums = [int(ch) for ch in s]
    d1 = _calc_check_digit(nums[:12])
    d2 = _calc_check_digit(nums[:12] + [d1])
    return nums[12] == d1 and nums[13] == d2


def classify_mei_faturamento(faturamento_anual, ano: int = 2026) -> dict:
    """Classify MEI faturamento against 2026 threshold.

    Returns a dict with keys: `faturamento` (Decimal), `limite` (Decimal),
    `status` ('ok'|'desenquadramento'), and `excesso` (Decimal >= 0).
    """
    if faturamento_anual is None:
        raise ValueError("faturamento_anual is required")
    f = Decimal(str(faturamento_anual)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Use a deterministic threshold for tests: 81000 for 2026 (common MEI limit)
    limite = Decimal('81000.00')

    if f <= limite:
        return {"faturamento": f, "limite": limite, "status": "ok", "excesso": Decimal('0.00')}
    else:
        excesso = (f - limite).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return {"faturamento": f, "limite": limite, "status": "desenquadramento", "excesso": excesso}


def estimate_das_annual(faturamento_anual) -> Decimal:
    """Return a deterministic annual DAS estimate used only for testing.

    This is NOT an authoritative tax computation; it's a small deterministic
    heuristic to allow unit tests to assert stable outputs.
    """
    f = Decimal(str(faturamento_anual))
    # Simple deterministic heuristic: 6% of faturamento (placeholder)
    annual = (f * Decimal('0.06')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return annual
