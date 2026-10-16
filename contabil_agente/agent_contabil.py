"""Ponto de entrada do agente contábil.

``AgenteContabil`` (cálculo + PDF + hash) vive em ``contabil_agente.agent``; o chat está em
``contabil_agente.chat``; a API HTTP em ``agente_v2``. Este módulo reúne o que é preciso para
usar o agente a partir de Python ou da linha de comando::

    python -m contabil_agente.agent_contabil
"""

from __future__ import annotations

import json
import sys

from contabil_agente.agent import AgenteContabil, inferir_tipo
from contabil_agente.persona import SYSTEM_PROMPT_MARIA_HELENA, obter_prompt

__all__ = ["AgenteContabil", "inferir_tipo", "SYSTEM_PROMPT_MARIA_HELENA", "obter_prompt"]


def _demo() -> int:
    exemplo = {"salario": 3000.00, "tipo_calculo": "folha"}
    saida = AgenteContabil().processar_pedido(exemplo)
    print(json.dumps(saida, ensure_ascii=False, indent=2, default=str))
    return 0 if saida.get("success") else 1


if __name__ == "__main__":
    sys.exit(_demo())
