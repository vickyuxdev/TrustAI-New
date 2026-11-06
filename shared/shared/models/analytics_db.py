"""
shared/models/analytics_db.py
TimescaleDB hypertable models for the analytics (time-series) store.
These live in a SEPARATE database from the metadata store.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalyticsBase(DeclarativeBase):
    pass


class SpanRecord(AnalyticsBase):
    """
    One row per span (LLM call, agent step, tool call, etc.).
    The primary time-series table — partitioned by timestamp via TimescaleDB.
    Schema is provider-neutral: all cloud providers normalise into this shape.
    """
    __tablename__ = "spans"

    # ─── Identity ───────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    span_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(128))

    # ─── Routing ────────────────────────────────────────────
    # FK references to metadata store (denormalized for query speed)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    environment: Mapped[str] = mapped_column(String(50), nullable=False, default="production")

    # ─── Span Classification ─────────────────────────────────
    span_name: Mapped[str] = mapped_column(String(255), nullable=False)
    span_kind: Mapped[str] = mapped_column(String(50), default="internal")  # "llm", "agent", "tool", "internal"

    # ─── Timing ──────────────────────────────────────────────
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ─── LLM-specific (provider-neutral) ─────────────────────
    provider: Mapped[str | None] = mapped_column(String(100))          # "azure_openai", "openai", "anthropic"
    model_name: Mapped[str | None] = mapped_column(String(255))        # "gpt-4o", "claude-3-5-sonnet"
    model_version: Mapped[str | None] = mapped_column(String(100))
    operation: Mapped[str | None] = mapped_column(String(100))         # "chat", "completion", "embedding"
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)

    # ─── Content capture (masked or full based on project config) ───
    input_content: Mapped[str | None] = mapped_column(Text)   # prompt / messages JSON
    output_content: Mapped[str | None] = mapped_column(Text)  # response content
    content_capture_mode: Mapped[str | None] = mapped_column(String(20))

    # ─── Status ──────────────────────────────────────────────
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_type: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)
    finish_reason: Mapped[str | None] = mapped_column(String(50))  # "stop", "length", "content_filter"

    # ─── Source Connector ────────────────────────────────────
    source_provider: Mapped[str] = mapped_column(String(100), default="trustai_sdk")  # connector that produced this
    raw_attributes: Mapped[dict] = mapped_column(JSONB, default=dict)  # original provider attributes

    # ─── Arbitrary tags for filtering ────────────────────────
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        # TimescaleDB will use `timestamp` for partitioning
        Index("ix_spans_trace_id", "trace_id"),
        Index("ix_spans_project_env_ts", "project_id", "environment", "timestamp"),
        Index("ix_spans_client_ts", "client_id", "timestamp"),
        Index("ix_spans_model_ts", "model_name", "timestamp"),
    )


class HourlyRollup(AnalyticsBase):
    """
    Pre-aggregated hourly metrics per (client, project, agent, model, environment).
    Computed by the processor worker from SpanRecord rows.
    Used by the dashboard for fast chart rendering.
    """
    __tablename__ = "hourly_rollups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # truncated to hour
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    environment: Mapped[str | None] = mapped_column(String(50))
    provider: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(255))

    total_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    successful_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    failed_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    avg_duration_ms: Mapped[float | None] = mapped_column(Float)
    p50_duration_ms: Mapped[float | None] = mapped_column(Float)
    p95_duration_ms: Mapped[float | None] = mapped_column(Float)
    p99_duration_ms: Mapped[float | None] = mapped_column(Float)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_hourly_rollups_hour_client", "hour", "client_id"),
        Index("ix_hourly_rollups_hour_project", "hour", "project_id"),
    )


class DailyRollup(AnalyticsBase):
    """Daily aggregates — same dimensions as HourlyRollup but per-day."""
    __tablename__ = "daily_rollups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # truncated to day
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    environment: Mapped[str | None] = mapped_column(String(50))
    provider: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(255))

    total_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    successful_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    failed_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    avg_duration_ms: Mapped[float | None] = mapped_column(Float)
    p50_duration_ms: Mapped[float | None] = mapped_column(Float)
    p95_duration_ms: Mapped[float | None] = mapped_column(Float)
    p99_duration_ms: Mapped[float | None] = mapped_column(Float)
    unique_agents: Mapped[int] = mapped_column(Integer, default=0)
    unique_models: Mapped[int] = mapped_column(Integer, default=0)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_daily_rollups_day_client", "day", "client_id"),
        Index("ix_daily_rollups_day_project", "day", "project_id"),
    )
