"""Personas do agente (MARCOS e Maria Helena). Os prompts vivem em ``core/prompts.py``."""

from contabil_agente.core.prompts import (
    MARIA_HELENA as SYSTEM_PROMPT_MARIA_HELENA,
    obter_prompt,
    personas_disponiveis,
)

__all__ = ["SYSTEM_PROMPT_MARIA_HELENA", "obter_prompt", "personas_disponiveis"]
