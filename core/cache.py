from __future__ import annotations
from functools import lru_cache
from datetime import date


class CalculationCache:
    """Cache wrapper for calculation results.

    Uses `functools.lru_cache` keyed by `salario_base` and `data_admissao`.
    """

    def __init__(self, maxsize: int = 1024) -> None:
        self._maxsize = maxsize

    def _make_key(self, salario_base: float, data_admissao: date) -> tuple:
        return (float(salario_base), data_admissao.isoformat())

    def cached(self, func):
        """Decorator to apply LRU caching to a calculation function.

        The wrapped function should accept `salario_base` and `data_admissao`.
        """

        @lru_cache(maxsize=self._maxsize)
        def _wrapped(salario_base: float, data_admissao_iso: str):
            # Convert back inside wrapper to match interface
            from datetime import date as _date

            return func(salario_base, _date.fromisoformat(data_admissao_iso))

        def decorator(salario_base: float, data_admissao: date):
            return _wrapped(salario_base, data_admissao.isoformat())

        decorator.cache_info = _wrapped.cache_info
        return decorator
