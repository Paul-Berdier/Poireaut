"""Application settings loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
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

    # ─── Auth ───
    jwt_secret: str = Field(default="change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=1440)
    allow_registration: bool = Field(default=True)

    # ─── Database ───
    database_url: str = Field(
        default="postgresql+asyncpg://poireaut:poireaut@postgres:5432/poireaut"
    )

    # ─── Redis / Celery ───
    redis_url: str = Field(default="redis://redis:6379/0")
    celery_broker_url: str = Field(default="redis://redis:6379/1")
    celery_result_backend: str = Field(default="redis://redis:6379/2")

    # ─── Validators ───

    @field_validator("database_url", mode="after")
    @classmethod
    def _ensure_asyncpg_driver(cls, v: str) -> str:
        """Accept any Postgres URL shape and coerce to asyncpg.

        Railway's Postgres addon exposes DATABASE_URL as `postgres://…` or
        `postgresql://…` (sync). Our engine is async so we swap the scheme.
        This makes the DATABASE_URL env var forgiving: you can feed it the
        raw `${{Postgres.DATABASE_URL}}` without having to reconstruct a new
        URL from the individual PG* parts.
        """
        if not v:
            return v
        if v.startswith("postgresql+asyncpg://"):
            return v
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
