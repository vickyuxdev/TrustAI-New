"""
services/gateway/app/config.py
TrustAI AI Gateway settings (environment / .env only) and the upstream model registry.

Upstreams come from TRUSTAI_GATEWAY_UPSTREAMS_FILE (YAML/JSON) or TRUSTAI_GATEWAY_UPSTREAMS (inline JSON):
  gpt-4o:
    provider: azure_openai            # azure_openai | openai (any OpenAI-compatible API: OpenAI, OpenRouter,
    base_url: https://x.openai.azure.com          LiteLLM, vLLM) | mock (development only)
    deployment: gpt-4o
    api_version: 2024-10-21
    api_key_env: AZURE_OPENAI_API_KEY  # secret read from this environment variable, never from the file
  oss-gpt-oss-120b:
    provider: openai
    base_url: https://openrouter.ai/api/v1
    model: openai/gpt-oss-120b
    api_key_env: OPENROUTER_API_KEY
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Upstream(BaseModel):
    """One model route."""

    provider: Literal["azure_openai", "openai", "mock"]
    base_url: str = ""
    model: str | None = None  # upstream model name (openai provider); defaults to the alias
    deployment: str | None = None  # azure_openai deployment name
    api_version: str = "2024-10-21"
    api_key_env: str | None = None
    timeout_seconds: float = 120.0

    def api_key(self) -> str:
        """Secret from the configured environment variable ('' when unset)."""
        return os.getenv(self.api_key_env, "") if self.api_key_env else ""


class GatewaySettings(BaseSettings):
    """Configuration of the gateway data plane."""

    environment: Literal["development", "staging", "production", "test"] = Field(
        default="development", alias="TRUSTAI_ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="TRUSTAI_LOG_LEVEL")
    governance_url: str = Field(default="http://localhost:8004", alias="TRUSTAI_GOVERNANCE_URL")
    internal_api_secret: SecretStr = Field(default=SecretStr("internal-secret-change-me"), alias="TRUSTAI_INTERNAL_API_SECRET")
    upstreams_file: str = Field(default="", alias="TRUSTAI_GATEWAY_UPSTREAMS_FILE")
    upstreams_json: str = Field(default="", alias="TRUSTAI_GATEWAY_UPSTREAMS")
    key_cache_seconds: float = Field(default=30.0, alias="TRUSTAI_GATEWAY_KEY_CACHE_SECONDS")
    rate_limit_rpm: int = Field(default=600, ge=1, alias="TRUSTAI_GATEWAY_RATE_LIMIT_RPM")
    enforce_timeout_seconds: float = Field(default=15.0, alias="TRUSTAI_GATEWAY_ENFORCE_TIMEOUT")
    fail_closed: bool = Field(default=True, alias="TRUSTAI_GATEWAY_FAIL_CLOSED")  # block when governance is down
    max_body_bytes: int = Field(default=2_000_000, alias="TRUSTAI_GATEWAY_MAX_BODY_BYTES")
    # Optional telemetry into TrustAI ingestion (spans show up in Traces / Cost).
    ingest_url: str = Field(default="", alias="TRUSTAI_INGEST_URL")
    ingest_api_key: SecretStr = Field(default=SecretStr(""), alias="TRUSTAI_GATEWAY_INGEST_API_KEY")
    ingest_project_id: str = Field(default="", alias="TRUSTAI_GATEWAY_INGEST_PROJECT_ID")
    cors_origins: list[str] = Field(default=["http://localhost:3000"], alias="TRUSTAI_CORS_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    def upstreams(self) -> dict[str, Upstream]:
        """Model alias -> upstream route. The mock provider is refused outside development/test."""
        raw: dict[str, Any] = {}
        if self.upstreams_file:
            # ${VAR} references (endpoints, never keys) are expanded from the environment
            text = os.path.expandvars(Path(self.upstreams_file).read_text(encoding="utf-8"))
            if self.upstreams_file.endswith((".yaml", ".yml")):
                import yaml

                raw = yaml.safe_load(text) or {}
            else:
                raw = json.loads(text)
        elif self.upstreams_json:
            raw = json.loads(self.upstreams_json)
        routes = {alias: Upstream.model_validate(spec) for alias, spec in raw.items()}
        if self.environment in ("staging", "production"):
            routes = {a: u for a, u in routes.items() if u.provider != "mock"}
        return routes


@lru_cache
def get_settings() -> GatewaySettings:
    """Process-wide settings singleton."""
    return GatewaySettings()
