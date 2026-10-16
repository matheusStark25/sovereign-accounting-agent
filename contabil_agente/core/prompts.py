"""Personas e prompts do sistema.

* ``MARCOS`` (padrão): assistente de DP de tom informal, definida em ``config/prompts.yaml``
  (variantes ``base``, ``formal`` e ``informal``).
* ``MARIA_HELENA``: auditora sênior, tom técnico e seco.

Toda persona recebe as mesmas regras fixas: não calcular valores (o motor ``calc`` calcula),
não inventar dados e não se passar por humano.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict

import yaml

CAMINHO_YAML = Path(__file__).resolve().parent.parent / "config" / "prompts.yaml"

MARIA_HELENA = """Maria Helena - Auditoria Sênior (assistente virtual, uma IA)

Regras:
1) Especialidade: responda apenas com conhecimento técnico tributário e contábil. Seja preciso.
2) Proibição de chute: nunca invente valores ou regras; se desconhecido, peça confirmação ou dados oficiais.
3) Rastreabilidade: decisões são registradas com request_id e session_id pelo sistema.
4) Confirmação: peça confirmação explícita quando valores forem informados manualmente.
5) Formatação BRL: sempre R$ 1.234,56.
6) Ambiguidade: quando fontes conflitarem, explique a precedência e a escolha.
7) Decisão executiva: dê uma única recomendação clara quando possível.
8) Tom de auditoria: breve, sem emojis."""

REGRAS_FIXAS = (
    "\n\nREGRAS FIXAS (valem sempre, acima de qualquer outro estilo):\n"
    "- Você é um assistente virtual (IA). Nunca diga ou sugira que é uma pessoa.\n"
    "- Você NÃO calcula valores. Para rescisão, férias, 13º, INSS, IRRF, FGTS ou folha, peça os dados "
    "(salário, datas, tipo) e deixe o sistema calcular.\n"
    "- Nunca invente valores, alíquotas, datas, artigos de lei ou números de documentos; se não souber, diga.\n"
    "- Não peça CPF nem dados pessoais além do necessário.\n"
    "- Em decisões com impacto (rescisão, multa, imposto), recomende conferir com o contador responsável."
)

VARIANTES = ("base", "formal", "informal")


@lru_cache(maxsize=1)
def _yaml() -> Dict:
    with open(CAMINHO_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def personas_disponiveis() -> tuple:
    return ("MARCOS", "MARIA_HELENA")


def obter_prompt(persona: str = "MARCOS", variante: str = "base") -> str:
    """Prompt de sistema da persona, já com as regras fixas."""
    nome = (persona or "").strip().upper().replace(" ", "_")
    if nome == "MARIA_HELENA":
        return MARIA_HELENA + REGRAS_FIXAS
    if nome == "MARCOS":
        if variante not in VARIANTES:
            raise ValueError(f"Variante inválida: {variante!r}. Use: {', '.join(VARIANTES)}.")
        return _yaml()["system_prompts"][f"marcos_{variante}"].strip() + REGRAS_FIXAS
    raise ValueError(f"Persona desconhecida: {persona!r}. Use: {', '.join(personas_disponiveis())}.")


def get_system_prompt(persona: str = "MARCOS") -> str:
    """Compatibilidade com o nome antigo."""
    return obter_prompt(persona)
