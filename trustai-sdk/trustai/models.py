"""
trustai/models.py
Provider-neutral data models for spans, LLM calls, and agent runs.
The SDK serialises these into the TrustAI Ingestion API payload format.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


SpanKind = Literal["llm", "agent", "tool", "retrieval", "internal"]
ContentCaptureMode = Literal["full", "masked", "disabled"]


class LLMUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None


class Span(BaseModel):
    """
    A single unit of work recorded by the SDK.
    Maps 1:1 to the IngestSpan schema on the server side.
    """
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: str | None = None
    span_name: str
    span_kind: SpanKind = "internal"

    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    duration_ms: float | None = None

    # Provider-neutral LLM metadata
    provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    operation: str | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)

    # Content (SDK will strip if project config says disabled/masked)
    input_content: str | None = None
    output_content: str | None = None
    content_capture_mode: ContentCaptureMode | None = None

    success: bool = True
    error_type: str | None = None
    error_message: str | None = None
    finish_reason: str | None = None

    tags: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)

    def finish(self, *, success: bool = True, error: Exception | None = None) -> None:
        self.ended_at = _utcnow()
        self.duration_ms = round(
            (self.ended_at - self.started_at).total_seconds() * 1000, 1
        )
        self.success = success
        if error:
            self.error_type = type(error).__name__
            self.error_message = str(error)

    def to_ingest_dict(self) -> dict[str, Any]:
        """Serialise to the IngestSpan wire format."""
        d = self.model_dump(mode="json", exclude_none=True)
        # Flatten LLMUsage into span
        usage = d.pop("usage", {})
        d.update({k: v for k, v in usage.items() if v is not None})
        return d


class AgentRun(BaseModel):
    """Represents a single execution of an agent (parent span)."""
    agent_name: str
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    environment: str = "production"
    started_at: datetime = Field(default_factory=_utcnow)
    spans: list[Span] = Field(default_factory=list)
    tags: dict[str, Any] = Field(default_factory=dict)
