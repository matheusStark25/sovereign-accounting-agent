from __future__ import annotations

from pydantic import BaseSettings, Field
from typing import Optional


class Settings(BaseSettings):
    # Vault
    VAULT_ADDR: Optional[str] = Field(None, env="VAULT_ADDR")
    VAULT_TOKEN: Optional[str] = Field(None, env="VAULT_TOKEN")

    # Redis
    REDIS_URL: Optional[str] = Field(None, env="REDIS_URL")

    # Rate limit
    RATE_LIMIT_PER_MINUTE: int = Field(600, env="RATE_LIMIT_PER_MINUTE")

    # Metrics
    METRICS_TOKEN: Optional[str] = Field(None, env="METRICS_TOKEN")

    # Cleanup
    RETENTION_HOURS: int = Field(24, env="RETENTION_HOURS")

    # Generic
    QUEUE_DIR: str = Field("./.queue", env="QUEUE_DIR")
    JOBS_DB: str = Field("./.jobs.db", env="JOBS_DB")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
