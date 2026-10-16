from __future__ import annotations

import os
from typing import Any


class Settings:
    """Lightweight settings shim that reads from environment.

    Avoids a hard dependency on pydantic so the test and runtime
    environment remains stable. Provides the small subset of settings
    required by the orchestrator/manager.
    """

    def __init__(self, env: Any = os.environ):
        self.db_timeout_seconds = int(env.get("AGENTE_DB_TIMEOUT_SECONDS", "1"))
        self.heartbeat_timeout = int(env.get("AGENTE_HEARTBEAT_TIMEOUT", "10"))
        self.task_timeout = int(env.get("AGENTE_TASK_TIMEOUT", "60"))
        self.outbox_flush_interval = int(env.get("AGENTE_OUTBOX_FLUSH_INTERVAL", "5"))
        if self.heartbeat_timeout >= self.task_timeout:
            raise ValueError("heartbeat_timeout must be less than task_timeout")


settings = Settings()

# Banco de dados
DB_NAME = "db/contabil.db"
BASE_DP = "db/base_dp.db"

# Memória agente
MEMORIA_LIMIT = 20

# API Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "SUA_CHAVE_AQUI"

# Prompt do agente - importe do `core.prompts` (fallback vazio se indisponível)
try:
    from core.prompts import SYSTEM_PROMPT
except Exception:
    SYSTEM_PROMPT = ""


class Config:
    # Compatibility wrapper for code importing Config from settings
    GROQ_API_KEY = GROQ_API_KEY
    MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.3"))
