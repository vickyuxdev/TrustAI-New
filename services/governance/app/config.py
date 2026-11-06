"""
services/governance/app/config.py
Governance-service settings. Every value comes from the environment (or `.env`); nothing secret is hard-coded.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GovernanceSettings(BaseSettings):
    """Configuration for the governance service, its guardrail engine and the evaluation worker."""

    environment: Literal["development", "staging", "production", "test"] = Field(
        default="development", alias="TRUSTAI_ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="TRUSTAI_LOG_LEVEL")

    # Governance tables live in the TrustAI metadata database (Postgres in every real deployment).
    database_url: str = Field(
        default="postgresql+asyncpg://trustai:trustai@localhost:5432/trustai", alias="TRUSTAI_POSTGRES_URL")
    db_pool_size: int = Field(default=10, alias="TRUSTAI_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="TRUSTAI_DB_MAX_OVERFLOW")
    create_tables_on_startup: bool = Field(default=True, alias="TRUSTAI_GOVERNANCE_CREATE_TABLES")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="TRUSTAI_REDIS_URL")
    # inline: evaluations run as background tasks in this process; redis: queued for the worker process.
    eval_executor: Literal["inline", "redis"] = Field(default="inline", alias="TRUSTAI_EVAL_EXECUTOR")
    eval_queue_name: str = Field(default="trustai:governance:evaluations", alias="TRUSTAI_EVAL_QUEUE")
    eval_concurrency: int = Field(default=4, ge=1, le=32, alias="TRUSTAI_EVAL_CONCURRENCY")
    eval_agent_timeout_seconds: float = Field(default=60.0, alias="TRUSTAI_EVAL_AGENT_TIMEOUT")
    eval_max_prompts: int = Field(default=500, alias="TRUSTAI_EVAL_MAX_PROMPTS")

    cors_origins: list[str] = Field(default=["http://localhost:3000"], alias="TRUSTAI_CORS_ORIGINS")
    internal_api_secret: SecretStr = Field(
        default=SecretStr("internal-secret-change-me"), alias="TRUSTAI_INTERNAL_API_SECRET")
    # Development/test only: "key=project_uuid[,key=project_uuid]" accepted without the admin service's api_keys
    # table (local runs without Postgres). Ignored in staging and production.
    static_keys: SecretStr = Field(default=SecretStr(""), alias="TRUSTAI_GOVERNANCE_STATIC_KEYS")

    # Public URLs used in responses (deep links, gateway endpoint handed to agents).
    portal_url: str = Field(default="http://localhost:3000", alias="TRUSTAI_PORTAL_URL")
    gateway_public_url: str = Field(default="http://localhost:8005", alias="TRUSTAI_GATEWAY_PUBLIC_URL")
    default_gateway_model: str = Field(default="gpt-4o", alias="TRUSTAI_GATEWAY_DEFAULT_MODEL")
    gateway_models: str = Field(default="", alias="TRUSTAI_GATEWAY_MODELS")  # comma list; empty = any registered

    # Observability wiring: the admin service issues ingest keys; agents send traces to the ingestion URL.
    admin_url: str = Field(default="http://localhost:8003", alias="TRUSTAI_ADMIN_URL")
    ingestion_public_url: str = Field(default="http://localhost:8001", alias="TRUSTAI_INGESTION_PUBLIC_URL")
    admin_timeout_seconds: float = Field(default=15.0, alias="TRUSTAI_ADMIN_TIMEOUT")

    # Guardrail engine backends (all optional - built-in detectors always work offline).
    content_safety_endpoint: str = Field(default="", alias="AZURE_CONTENT_SAFETY_ENDPOINT")
    content_safety_key: SecretStr = Field(default=SecretStr(""), alias="AZURE_CONTENT_SAFETY_KEY")
    judge_provider: Literal["none", "openai", "azure_openai"] = Field(default="none", alias="TRUSTAI_JUDGE_PROVIDER")
    judge_base_url: str = Field(default="", alias="TRUSTAI_JUDGE_BASE_URL")
    judge_api_key: SecretStr = Field(default=SecretStr(""), alias="TRUSTAI_JUDGE_API_KEY")
    judge_model: str = Field(default="gpt-4o-mini", alias="TRUSTAI_JUDGE_MODEL")
    judge_api_version: str = Field(default="2024-10-21", alias="TRUSTAI_JUDGE_API_VERSION")
    engine_timeout_seconds: float = Field(default=8.0, alias="TRUSTAI_ENGINE_TIMEOUT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def is_dev(self) -> bool:
        """True when unauthenticated dashboard calls may fall back to the development super-admin."""
        return self.environment in ("development", "test")


@lru_cache
def get_settings() -> GovernanceSettings:
    """Process-wide settings singleton (tests clear the cache to re-read the environment)."""
    return GovernanceSettings()
