"""Application settings loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration lives here.

    Values are populated from environment variables. In local dev, docker-compose
    reads .env and injects them. In production, Railway injects them directly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── App ───
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # ─── API ───
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_cors_origins: str = Field(default="http://localhost:5173")

    # ─── Database ───
    database_url: str = Field(
        default="postgresql+asyncpg://poireaut:poireaut@postgres:5432/poireaut"
    )

    # ─── Redis / Celery ───
    redis_url: str = Field(default="redis://redis:6379/0")
    celery_broker_url: str = Field(default="redis://redis:6379/1")
    celery_result_backend: str = Field(default="redis://redis:6379/2")

    @property
    def cors_origins_list(self) -> list[str]:
        """Split the comma-separated CORS origins string into a list."""
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor — settings are loaded once per process."""
    return Settings()
