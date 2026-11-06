"""
shared/models/schemas.py
Pydantic v2 request/response schemas shared across all services.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.models.db import AlertSeverity, AlertStatus, ApiKeyStatus, ClientType, ConnectorProvider, ContentCaptureMode, UserRole


# ─────────────────────────────────────────────
# Common
# ─────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[Any]


# ─────────────────────────────────────────────
# Ingestion Schemas (SDK → Ingestion Service)
# ─────────────────────────────────────────────

class IngestSpan(BaseModel):
    """Single span submitted by the TrustAI SDK."""
    model_config = ConfigDict(extra="allow")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    span_name: str
    span_kind: str = "internal"

    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = None

    # LLM fields (all optional — non-LLM spans won't have these)
    provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    operation: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None

    # Content (may be stripped by SDK based on project config)
    input_content: str | None = None
    output_content: str | None = None

    success: bool = True
    error_type: str | None = None
    error_message: str | None = None
    finish_reason: str | None = None

    tags: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class IngestBatch(BaseModel):
    """Batch of spans submitted by the SDK in one API call."""
    project_id: uuid.UUID
    environment: str = "production"
    agent_name: str | None = None
    sdk_version: str | None = None
    spans: list[IngestSpan]


# ─────────────────────────────────────────────
# Client Schemas
# ─────────────────────────────────────────────

class ClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9-]+$", min_length=2, max_length=100)
    client_type: ClientType
    description: str | None = None
    monthly_budget_usd: float | None = None


class ClientUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    monthly_budget_usd: float | None = None


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    client_type: ClientType
    description: str | None
    is_active: bool
    monthly_budget_usd: float | None
    created_at: datetime
    # Analytics summary injected by API layer
    total_cost_usd: float | None = None
    total_calls: int | None = None
    active_projects: int | None = None


# ─────────────────────────────────────────────
# Project Schemas
# ─────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9-]+$", min_length=2, max_length=100)
    description: str | None = None
    content_capture_mode: ContentCaptureMode = ContentCaptureMode.MASKED
    content_capture_overrides: dict[str, ContentCaptureMode] = Field(default_factory=dict)
    monthly_budget_usd: float | None = None
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content_capture_mode: ContentCaptureMode | None = None
    content_capture_overrides: dict[str, ContentCaptureMode] | None = None
    is_active: bool | None = None
    monthly_budget_usd: float | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    content_capture_mode: ContentCaptureMode
    content_capture_overrides: dict
    is_active: bool
    monthly_budget_usd: float | None
    tags: list
    created_at: datetime
    total_cost_usd: float | None = None
    total_calls: int | None = None


# ─────────────────────────────────────────────
# API Key Schemas
# ─────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default=["ingest"])
    expires_at: datetime | None = None


class ApiKeyCreateResponse(BaseModel):
    """Returned only once on creation — includes the raw key."""
    id: uuid.UUID
    name: str
    key_prefix: str
    raw_key: str  # ONLY returned on creation; never stored
    scopes: list[str]
    created_at: datetime


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    status: ApiKeyStatus
    scopes: list
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


# ─────────────────────────────────────────────
# Analytics / Dashboard Schemas
# ─────────────────────────────────────────────

class TimeRange(BaseModel):
    start: datetime
    end: datetime
    granularity: str = "hour"  # "hour", "day", "week"


class OverviewMetrics(BaseModel):
    period_start: datetime
    period_end: datetime
    total_cost_usd: float
    total_calls: int
    total_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    error_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    active_projects: int
    active_agents: int
    cost_trend_pct: float  # % change vs previous period
    calls_trend_pct: float


class CostBreakdown(BaseModel):
    by_client: list[dict[str, Any]]
    by_project: list[dict[str, Any]]
    by_model: list[dict[str, Any]]
    by_provider: list[dict[str, Any]]
    by_environment: list[dict[str, Any]]
    by_agent: list[dict[str, Any]] = Field(default_factory=list)
    time_series: list[dict[str, Any]]
    top_projects: list[dict[str, Any]] = Field(default_factory=list)


class SpanDetail(BaseModel):
    """Full span detail for the trace waterfall view."""
    id: uuid.UUID
    trace_id: str
    span_id: str
    parent_span_id: str | None
    span_name: str
    span_kind: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: float | None
    provider: str | None
    model_name: str | None
    operation: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    input_content: str | None
    output_content: str | None
    content_capture_mode: str | None
    success: bool
    error_type: str | None
    error_message: str | None
    finish_reason: str | None
    tags: dict
    attributes: dict
    client_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    source_provider: str | None = None
    connector_id: str | None = None
    connector_name: str | None = None
    children: list["SpanDetail"] = Field(default_factory=list)


SpanDetail.model_rebuild()


# ─────────────────────────────────────────────
# Model Pricing Schemas
# ─────────────────────────────────────────────

class ModelPricingCreate(BaseModel):
    provider: str
    model_name: str
    model_version: str | None = None
    input_price_per_1m: float = Field(ge=0)
    output_price_per_1m: float = Field(ge=0)
    cached_input_price_per_1m: float | None = Field(default=None, ge=0)
    reasoning_price_per_1m: float | None = Field(default=None, ge=0)
    effective_from: datetime | None = None


class ModelPricingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    model_name: str
    model_version: str | None
    input_price_per_1m: float
    output_price_per_1m: float
    cached_input_price_per_1m: float | None
    reasoning_price_per_1m: float | None
    effective_from: datetime
    is_active: bool


# ─────────────────────────────────────────────
# Connector Schemas
# ─────────────────────────────────────────────

class ConnectorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    provider: ConnectorProvider
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    provider: ConnectorProvider
    is_active: bool
    config: dict
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None
    created_at: datetime


# ─────────────────────────────────────────────
# Alert Schemas
# ─────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    name: str
    metric: str
    operator: str = Field(pattern=r"^(gt|lt|gte|lte|eq)$")
    threshold: float
    window_minutes: int = 60
    severity: AlertSeverity = AlertSeverity.WARNING
    notification_channels: list[str] = Field(default_factory=list)
    project_id: uuid.UUID | None = None


class AlertRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    metric: str
    operator: str
    threshold: float
    window_minutes: int
    severity: AlertSeverity
    notification_channels: list
    is_active: bool
    created_at: datetime


class FiredAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    status: AlertStatus
    triggered_value: float
    message: str
    triggered_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


# ─────────────────────────────────────────────
# User / Auth Schemas
# ─────────────────────────────────────────────

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_super_admin: bool
    last_login_at: datetime | None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
