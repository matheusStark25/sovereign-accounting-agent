"""
Funções auxiliares do sistema
Conversões, formatações e utilitários gerais
"""

import json


def _ensure_resposta_str(value):
    """
    Garante que resposta_ia seja sempre string válida UTF-8
    Remove caracteres problemáticos (emojis inválidos, surrogates)

    Args:
        value: Qualquer valor (str, dict, list, etc)

    Returns:
        String UTF-8 válida
    """
    if isinstance(value, str):
        # Remove surrogates (emojis inválidos) que causam erro UTF-8
        return value.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")

    try:
        # Pretty print objetos mas evita escape ASCII (mantém UTF-8)
        json_str = json.dumps(value, ensure_ascii=False)
        # Sanitiza surrogates no JSON
        return json_str.encode("utf-8", errors="ignore").decode(
            "utf-8", errors="ignore"
        )
    except Exception:
        try:
            str_value = str(value)
            return str_value.encode("utf-8", errors="ignore").decode(
                "utf-8", errors="ignore"
            )
        except Exception:
            return ""
