from __future__ import annotations
from typing import Optional
from pathlib import Path

# Pydantic v2 moved BaseSettings to pydantic-settings package
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    try:
        from pydantic import BaseSettings
        from pydantic import SettingsConfigDict
    except ImportError:
        # Fallback: create minimal stubs
        BaseSettings = object
        SettingsConfigDict = lambda **kw: {}


class Settings(BaseSettings):
    """Application settings validated via pydantic-settings.

    Values are loaded from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    INPUT_PATH: Path = Path("data/input")
    OUTPUT_PATH: Path = Path("data/output")
    LOG_PATH: Path = Path("audits.log")
    SIGNATURE_KEY: Optional[str] = None
    CHECKPOINT_FILE: Path = Path(".progress")
    COMPANY_NAME: str = "Agente Contábil"


def load_settings() -> Settings:
    return Settings()


"""Minimal Config stub for local validation runs."""


class Config:
    """Simple configuration container used as a compatibility shim."""

    def __init__(self, **kwargs):
        self._data = kwargs

    def get(self, key, default=None):
        return self._data.get(key, default)

    @staticmethod
    def load(*args, **kwargs):
        return Config()
