"""Application settings.

Configuration is centralized and validated at startup (AGENTS.md §6).
Secrets must not get production-usable defaults: values below are local-only
placeholders and must be overridden via environment/.env in any shared environment.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
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

    # Stage 5: service authentication of the existing bot calling our webhook
    # (11.A.1 is an open question; shared-secret header is the PROPOSED measure,
    # token lives outside Support Hub, sent by the bot in Authorization: Bearer).
    # Local-only placeholder; MUST be overridden in any shared environment.
    bot_webhook_token: str = Field(
        default="CHANGE_ME_LOCAL_ONLY_BOT_TOKEN",
        validation_alias=AliasChoices("BOT_TO_SUPPORT_HUB_TOKEN", "BOT_WEBHOOK_TOKEN"),
    )
    # Where the bot's own API lives (PROPOSED contract, POST /internal/v1/tag/messages;
    # must be verified against the actual bot implementation, D-028).
    bot_internal_base_url: str = Field(
        default="http://localhost:8080",
        validation_alias=AliasChoices(
            "MATTERMOST_BOT_INTERNAL_BASE_URL", "BOT_INTERNAL_BASE_URL"
        ),
    )
    # Optional service token for Support Hub -> bot outbound calls (PROPOSED;
    # empty means no Authorization header until the real bot contract is known).
    support_hub_to_bot_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPPORT_HUB_TO_BOT_TOKEN", "SUPPORT_HUB_TO_BOT_TOKEN_LOCAL"
        ),
    )

    # Stage 6: RAG Assistant Gateway (real contract D-043, owner-provided
    # 2026-11-10): synchronous HTTP, X-API-Key + X-User-Id headers, no
    # callbacks. The gateway keeps its own context; we never send history.
    ai_gateway_base_url: str = Field(
        default="https://ai-gateway.invalid",
        validation_alias=AliasChoices(
            "AI_ORCHESTRATOR_BASE_URL", "AI_GATEWAY_BASE_URL"
        ),
    )
    # The API key is issued by the gateway integration team, lives outside git.
    ai_gateway_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPPORT_HUB_TO_AI_TOKEN", "AI_GATEWAY_API_KEY"),
    )
    # Contract §5: LLM answers take 30-60 s; client timeout MUST be >= 130 s.
    ai_gateway_timeout_seconds: float = 130.0
    # Trigger codes (D-043 §7). Codes can be rotated on the gateway side; the
    # integration team must be notified in advance - update these then.
    ai_trigger_resolved_code: str = "hnQRDemsuPZY"
    ai_trigger_operator_code: str = "tY7Ve077FyZR1"

    # Stage 7: operator workspace authentication (docs/08 §1). Target is
    # Keycloak OIDC (Q-09: issuer/client unknown yet); pass 1 uses a shared
    # dev token + email header, local environment only. Local-only default.
    operator_dev_token: str = "CHANGE_ME_LOCAL_ONLY_OPERATOR_TOKEN"
    # When set (corporate env), operator endpoints demand real OIDC and
    # dev-token auth is refused (fail-closed, see app/auth/operators.py).
    keycloak_issuer_url: str = Field(
        default="", validation_alias=AliasChoices("OIDC_ISSUER_URL", "KEYCLOAK_ISSUER_URL")
    )
    keycloak_client_id: str = Field(
        default="support-hub", validation_alias=AliasChoices("OIDC_CLIENT_ID", "KEYCLOAK_CLIENT_ID")
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings; raises on invalid environment at first access."""
    return Settings()  # populated from environment
