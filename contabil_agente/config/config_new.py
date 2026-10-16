"""
Configurações centralizadas da aplicação
Usa variáveis de ambiente para produção
"""

import os
import secrets
from pathlib import Path
from typing import Optional

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Configurações da aplicação"""

    # ===== SEGURANÇA =====
    SECRET_KEY: str = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION: int = int(os.getenv("JWT_EXPIRATION", "86400"))  # 24 horas

    # ===== GROQ API =====
    GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.3"))

    # ===== SERVIDOR =====
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
    WORKERS: int = int(os.getenv("WORKERS", "4"))

    # ===== DIRETÓRIOS =====
    DOCUMENTS_DIR: Path = BASE_DIR / "documents"
    ASSINATURAS_DIR: Path = BASE_DIR / "assinaturas"
    LOGOS_DIR: Path = BASE_DIR / "logos"
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    LOGS_DIR: Path = BASE_DIR / "logs"
    DB_DIR: Path = BASE_DIR / "database"

    # ===== BANCO DE DADOS =====
    DB_PATH: Path = DB_DIR / "contabil_agent.db"
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))

    # ===== RATE LIMITING =====
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "True").lower() in (
        "1",
        "true",
        "yes",
    )
    RATE_LIMIT_DEFAULTS: str = os.getenv(
        "RATE_LIMIT_DEFAULTS", "200 per day,50 per hour"
    )
    RATELIMIT_STORAGE_URI: Optional[str] = os.getenv("RATELIMIT_STORAGE_URI")

    # ===== CORS =====
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")
    CORS_SUPPORTS_CREDENTIALS: bool = os.getenv(
        "CORS_SUPPORTS_CREDENTIALS", "false"
    ).lower() in (
        "1",
        "true",
        "yes",
    )

    # ===== UPLOAD =====
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", str(5 * 1024 * 1024)))
    ALLOWED_EXTENSIONS: set = {"pd", "png", "jpg", "jpeg", "json"}

    # ===== AWS S3 =====
    AWS_S3_BUCKET: Optional[str] = os.getenv("AWS_S3_BUCKET")
    AWS_REGION: Optional[str] = os.getenv("AWS_REGION")

    # ===== ADMIN =====
    ADMIN_USER: str = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "changeme")

    # ===== TOM DE VOZ =====
    TOM_VOZ: str = os.getenv("TOM_VOZ", "informal")

    @classmethod
    def validate(cls):
        """Valida configurações"""
        if not cls.GROQ_API_KEY:
            import warnings

            warnings.warn("GROQ_API_KEY não definida", RuntimeWarning)

        for dir_path in [
            cls.DOCUMENTS_DIR,
            cls.ASSINATURAS_DIR,
            cls.LOGOS_DIR,
            cls.UPLOADS_DIR,
            cls.LOGS_DIR,
            cls.DB_DIR,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)


Config.validate()
