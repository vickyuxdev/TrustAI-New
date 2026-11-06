"""
shared/config.py
Central settings management using Pydantic BaseSettings.
Each service imports and extends this as needed.
"""
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    # PostgreSQL — metadata store
    postgres_url: str = Field(
        default="postgresql+asyncpg://trustai:trustai@localhost:5432/trustai",
        alias="TRUSTAI_POSTGRES_URL",
    )
    # TimescaleDB / PostgreSQL — analytics store (can be same or separate instance)
    analytics_db_url: str = Field(
        default="postgresql+asyncpg://trustai:trustai@localhost:5433/trustai_analytics",
        alias="TRUSTAI_ANALYTICS_DB_URL",
    )
    db_pool_size: int = Field(default=10, alias="TRUSTAI_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="TRUSTAI_DB_MAX_OVERFLOW")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class RedisSettings(BaseSettings):
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="TRUSTAI_REDIS_URL",
    )
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AzureADSettings(BaseSettings):
    tenant_id: str = Field(default="default-tenant", alias="AZURE_TENANT_ID")
    client_id: str = Field(default="default-client-id", alias="AZURE_CLIENT_ID")
    client_secret: SecretStr = Field(default=SecretStr("default-secret"), alias="AZURE_CLIENT_SECRET")
    authority: str = ""
    # Scopes for the TrustAI API (set to your App Registration's Application ID URI)
    api_scope: str = Field(
        default="api://trustai/.default",
        alias="TRUSTAI_API_SCOPE",
    )
    # Allowed audience for JWT validation
    audience: str = Field(default="", alias="TRUSTAI_AZURE_AUDIENCE")

    @field_validator("authority", mode="before")
    @classmethod
    def build_authority(cls, v, info):
        if not v:
            tenant = info.data.get("tenant_id", "default-tenant") if info.data else "default-tenant"
            return f"https://login.microsoftonline.com/{tenant}"
        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class EventHubSettings(BaseSettings):
    connection_string: SecretStr = Field(
        default=SecretStr(""),
        alias="AZURE_EVENTHUB_CONNECTION_STRING",
    )
    eventhub_name: str = Field(
        default="trustai-telemetry",
        alias="AZURE_EVENTHUB_NAME",
    )
    consumer_group: str = Field(
        default="$Default",
        alias="AZURE_EVENTHUB_CONSUMER_GROUP",
    )
    checkpoint_store_url: str = Field(
        default="",
        alias="AZURE_EVENTHUB_CHECKPOINT_URL",
    )
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AppInsightsSettings(BaseSettings):
    connection_string: SecretStr = Field(
        default=SecretStr(""),
        alias="APPLICATIONINSIGHTS_CONNECTION_STRING",
    )
    workspace_id: str = Field(default="", alias="AZURE_LOG_ANALYTICS_WORKSPACE_ID")
    workspace_key: SecretStr = Field(
        default=SecretStr(""),
        alias="AZURE_LOG_ANALYTICS_WORKSPACE_KEY",
    )
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class JWTSettings(BaseSettings):
    secret_key: SecretStr = Field(
        default=SecretStr("change-me-in-production-use-256bit-random-key"),
        alias="TRUSTAI_JWT_SECRET",
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class BaseServiceSettings(
    DatabaseSettings,
    RedisSettings,
    AzureADSettings,
    JWTSettings,
):
    service_name: str = "trustai"
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        alias="TRUSTAI_ENVIRONMENT",
    )
    log_level: str = Field(default="INFO", alias="TRUSTAI_LOG_LEVEL")
    cors_origins: list[AnyHttpUrl] = Field(
        default=["http://localhost:3000"],
        alias="TRUSTAI_CORS_ORIGINS",
    )
    internal_api_secret: SecretStr = Field(
        default=SecretStr("internal-secret-change-me"),
        alias="TRUSTAI_INTERNAL_API_SECRET",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> BaseServiceSettings:
    return BaseServiceSettings()
