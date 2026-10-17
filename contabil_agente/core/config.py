"""Caminhos e opções do sistema, lidos do ambiente.

Não há valores secretos padrão aqui (nem senha de administrador, nem chave de API). Segredos
são lidos por ``agente_v2.vault_client.carregar_segredos`` (Vault primeiro, ambiente depois).
As pastas só são criadas quando ``Config.criar_pastas()`` é chamado, nunca no import.
"""

from __future__ import annotations

import os
from pathlib import Path


class Config:
    BASE_DIR = str(Path(os.getenv("BASE_DIR") or Path(__file__).resolve().parent.parent))
    DOCUMENTS_DIR = str(Path(BASE_DIR) / "documents")
    ASSINATURAS_DIR = str(Path(BASE_DIR) / "assinaturas")
    LOGOS_DIR = str(Path(BASE_DIR) / "logos")
    UPLOADS_DIR = str(Path(BASE_DIR) / "uploads")
    LOGS_DIR = str(Path(BASE_DIR) / "logs")
    DB_DIR = str(Path(BASE_DIR) / "db")
    DB_PATH = str(Path(BASE_DIR) / "db" / "contabil_agent.db")

    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    MODEL_NAME = os.getenv("AI_MODEL", "openai/gpt-oss-120b")
    TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.2"))
    VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH")
    TOM_VOZ = os.getenv("TOM_VOZ", "informal")
    AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
    AWS_REGION = os.getenv("AWS_REGION")

    @classmethod
    def criar_pastas(cls) -> None:
        for pasta in (cls.DOCUMENTS_DIR, cls.ASSINATURAS_DIR, cls.LOGOS_DIR, cls.UPLOADS_DIR, cls.LOGS_DIR, cls.DB_DIR):
            Path(pasta).mkdir(parents=True, exist_ok=True)


AppConfig = Config  # nome antigo, usado por alguns serviços
