# Utils module - Utilitários e helpers do sistema
from .audit import register_document_hash_in_governance
from .audit import send_audit
from .evolution import CalculationLogger
from .evolution import EvolutionManager
from .helpers import _ensure_resposta_str

# exported utility functions moved from the large agent module
from .common import (
    parse_brl_to_float,
    format_brl,
    _is_approximate_text,
    _normalize_k_suffix,
    safe_decimal,
    _is_small_talk,
)

__all__ = [
    "send_audit",
    "register_document_hash_in_governance",
    "_ensure_resposta_str",
    "EvolutionManager",
    "CalculationLogger",
    # new exports
    "parse_brl_to_float",
    "format_brl",
    "_is_approximate_text",
    "_normalize_k_suffix",
    "safe_decimal",
    "_is_small_talk",
]
