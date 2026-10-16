try:
    from pydantic import BaseSettings  # type: ignore[reportMissingImports]

    class Settings(BaseSettings):
        PROJECT_NAME: str = "Agente Contabil V2"
        SECRET_KEY: str = "dev-secret-change-me"
        ALGORITHM: str = "HS256"
        ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

        VAULT_URL: str | None = "http://127.0.0.1:8200"
        VAULT_TOKEN: str | None = None

        # Storage / infra placeholders
        MINIO_ENDPOINT: str | None = None
        MINIO_ACCESS_KEY: str | None = None
        MINIO_SECRET_KEY: str | None = None
        S3_BUCKET: str | None = None
        POSTGRES_DSN: str | None = None
        PROMETHEUS_ENABLED: bool = False

        class Config:
            env_file = ".env"

    settings = Settings()
except Exception:
    # Minimal fallback settings if pydantic isn't available during tests
    import os

    class _Settings:
        PROJECT_NAME = os.environ.get("PROJECT_NAME", "Agente Contabil V2")
        SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
        ALGORITHM = os.environ.get("ALGORITHM", "HS256")
        ACCESS_TOKEN_EXPIRE_MINUTES = int(
            os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
        )

        VAULT_URL = os.environ.get("VAULT_URL", "http://127.0.0.1:8200")
        VAULT_TOKEN = os.environ.get("VAULT_TOKEN")

        MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT")
        MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY")
        MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY")
        S3_BUCKET = os.environ.get("S3_BUCKET")
        POSTGRES_DSN = os.environ.get("POSTGRES_DSN")
        PROMETHEUS_ENABLED = os.environ.get("PROMETHEUS_ENABLED", "False").lower() in (
            "1",
            "true",
            "yes",
        )

    settings = _Settings()
