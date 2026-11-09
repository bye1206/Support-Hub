"""Application settings.

Configuration is centralized and validated at startup (AGENTS.md §6).
Secrets must not get production-usable defaults: values below are local-only
placeholders and must be overridden via environment/.env in any shared environment.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "staging", "prod"] = "local"
    app_name: str = "support-hub"
    app_base_url: str = "http://localhost"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Declared in bootstrap so that .env / docker-compose stay stable.
    # Real clients are implemented at stage 2 (implementation plan).
    # Local-only default; must be overridden outside the developer machine.
    database_url: str = (
        "postgresql+asyncpg://support_hub:support_hub@localhost:5432/support_hub"
    )
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (stage 5, attachments; D-016/D-020). Not probed by /readyz
    # and not part of the local dev stack — the corporate network provides storage.
    minio_endpoint: str = "localhost:9000"
    minio_secure: bool = False
    # MinIO product defaults; acceptable for local dev only, override in shared envs.
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "support-hub-files"

    # Maximum time one readiness probe may take before the dependency counts as down.
    # Generous default: first connection on a cold machine can be slow (IPv6 fallback).
    readiness_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    """Return cached settings; raises on invalid environment at first access."""
    return Settings()  # populated from environment
