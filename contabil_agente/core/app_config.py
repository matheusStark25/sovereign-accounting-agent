"""
Configurações centralizadas da aplicação
Todos os valores hardcoded devem vir daqui
"""

import os
from pathlib import Path


class AppConfig:
    """Configurações principais da aplicação"""

    # === Paths ===
    BASE_DIR = Path(__file__).parent.parent
    TEMP_FOLDER = BASE_DIR / "temp_docs"
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    DB_FOLDER = BASE_DIR / "db"
    SESSIONS_DB = DB_FOLDER / "sessions.db"

    # === Flask ===
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    JSON_AS_ASCII = False

    # === API Keys ===
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

    # === AI/LLM ===
    AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")
    AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.2"))  # Mais focada
    AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "800"))  # Respostas mais curtas
    AI_TOP_P = float(os.getenv("AI_TOP_P", "0.85"))  # Mais determinística

    # === Session Management ===
    SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "1800"))  # 30 min
    MAX_SESSION_MESSAGES = int(os.getenv("MAX_SESSION_MESSAGES", "15"))

    # === Rate Limiting ===
    RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # segundos
    RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "20"))
    RATE_LIMIT_MAX_CHARS = int(os.getenv("RATE_LIMIT_MAX_CHARS", "10000"))

    # === Security ===
    ALLOWED_EXTENSIONS = {"pd", "png", "jpg", "jpeg", "xlsx", "xls", "csv"}
    MAX_FILENAME_LENGTH = 100

    # === Logging ===
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def create_folders(cls):
        """Cria pastas necessárias se não existirem"""
        cls.TEMP_FOLDER.mkdir(exist_ok=True, parents=True)
        cls.UPLOAD_FOLDER.mkdir(exist_ok=True, parents=True)
        cls.DB_FOLDER.mkdir(exist_ok=True, parents=True)

    @classmethod
    def validate(cls):
        """Valida configurações essenciais"""
        if not cls.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY não configurada! Configure no .env")

        cls.create_folders()
        return True


# Inicialização automática
AppConfig.create_folders()
