from pathlib import Path

try:
    from pydantic_settings import BaseSettings
except Exception:
    try:
        from pydantic import BaseSettings
    except Exception:  # pragma: no cover - best-effort fallback
        BaseSettings = object

from pydantic import ConfigDict


class IASettings(BaseSettings):
    model_config = ConfigDict(env_prefix="IA_", extra="ignore")

    LOG_DIR: Path = Path("logs/ia")
    LLM_ENDPOINT: str | None = None
