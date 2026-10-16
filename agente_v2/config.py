"""Configuração por variáveis de ambiente (lida no momento do uso, sem valores secretos padrão)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _bool(nome: str, padrao: bool = False) -> bool:
    return os.environ.get(nome, str(padrao)).strip().lower() in ("1", "true", "yes", "sim")


class _Settings:
    @property
    def PROJECT_NAME(self) -> str:
        return os.environ.get("PROJECT_NAME", "Sovereign Accounting Agent")

    @property
    def ENV(self) -> str:
        return os.environ.get("AGENTE_ENV", "production").lower()

    @property
    def DATA_DIR(self) -> Path:
        padrao = Path(__file__).resolve().parent.parent / "contabil_agente" / "data"
        return Path(os.environ.get("DATA_DIR") or padrao)

    @property
    def CHAT_DB_PATH(self) -> str:
        return os.environ.get("CHAT_DB_PATH") or str(self.DATA_DIR / "chat.db")

    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        bruto = os.environ.get("ALLOWED_ORIGINS", "")
        return [o.strip() for o in bruto.split(",") if o.strip()]

    @property
    def VAULT_URL(self) -> Optional[str]:
        return os.environ.get("VAULT_ADDR") or os.environ.get("VAULT_URL")

    @property
    def VAULT_TOKEN(self) -> Optional[str]:
        return os.environ.get("VAULT_TOKEN")

    @property
    def MINIO_ENDPOINT(self) -> Optional[str]:
        return os.environ.get("MINIO_ENDPOINT")

    @property
    def MINIO_ACCESS_KEY(self) -> Optional[str]:
        return os.environ.get("MINIO_ACCESS_KEY")

    @property
    def MINIO_SECRET_KEY(self) -> Optional[str]:
        return os.environ.get("MINIO_SECRET_KEY")

    @property
    def S3_BUCKET(self) -> Optional[str]:
        return os.environ.get("S3_BUCKET")

    @property
    def POSTGRES_DSN(self) -> Optional[str]:
        return os.environ.get("POSTGRES_DSN")

    @property
    def PROMETHEUS_ENABLED(self) -> bool:
        return _bool("PROMETHEUS_ENABLED", True)


settings = _Settings()
