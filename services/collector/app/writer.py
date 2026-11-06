"""
services/collector/app/writer.py
Writes normalised LLM spans into the spans table (for trace waterfalls)
and upserts ConnectorMetric records into daily_rollups (for overview dashboard charts).
"""
import uuid
from datetime import datetime, date, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConnectorMetric
from shared.db.session import get_analytics_session, get_metadata_session
from shared.models.analytics_db import DailyRollup, SpanRecord
from shared.models.db import Project

log = structlog.get_logger()


async def write_spans(
    spans: list[dict[str, Any]],
    client_id: str | uuid.UUID,
    project_id: str | uuid.UUID | None = None,
) -> int:
    """
    Persist individual span records into the analytics DB spans table.
    Deduplicates by (trace_id, span_id).
    Returns the count of new spans written.
    """
    if not spans:
        return 0

    c_id = uuid.UUID(str(client_id))
    p_id = uuid.UUID(str(project_id)) if project_id else None

    # If project_id not provided on connector, resolve default project for client
    if not p_id:
        try:
            async with get_metadata_session() as m_session:
                res = await m_session.execute(
                    select(Project.id).where(Project.client_id == c_id).limit(1)
                )
                p_id = res.scalar_one_or_none()
        except Exception as exc:
            log.warning("writer.project_resolve_failed", error=str(exc))

    if not p_id:
        p_id = c_id  # Fallback to client_id GUID to satisfy non-null constraint

    written = 0
    async with get_analytics_session() as session:
        for s in spans:
            trace_id = s.get("trace_id", "")
            span_id = s.get("span_id", "")

            # Check for existing span to prevent duplicate ingestion
            existing = await session.execute(
                select(SpanRecord.id).where(
                    SpanRecord.trace_id == trace_id,
                    SpanRecord.span_id == span_id,
                ).limit(1)
            )
            if existing.scalar_one_or_none():
                continue

            started_at = s.get("started_at") or datetime.now(timezone.utc)
            ended_at = s.get("ended_at")

            rec = SpanRecord(
                id=uuid.uuid4(),
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=s.get("parent_span_id"),
                client_id=c_id,
                project_id=p_id,
                environment="production",
                span_name=s.get("span_name", "chat_completion_turn"),
                span_kind=s.get("span_kind", "llm"),
                timestamp=started_at,
                duration_ms=s.get("duration_ms"),
                started_at=started_at,
                ended_at=ended_at,
                provider=s.get("provider", "azure_openai"),
                model_name=s.get("model_name", "gpt-4o"),
                operation=s.get("operation", "chat"),
                input_tokens=s.get("input_tokens", 0),
                output_tokens=s.get("output_tokens", 0),
                total_tokens=s.get("total_tokens", 0),
                cached_tokens=s.get("cached_tokens", 0),
                reasoning_tokens=s.get("reasoning_tokens", 0),
                cost_usd=s.get("cost_usd", 0.0),
                input_content=s.get("input_content"),
                output_content=s.get("output_content"),
                content_capture_mode=s.get("content_capture_mode", "full"),
                success=s.get("success", True),
                error_type=s.get("error_type"),
                error_message=s.get("error_message"),
                finish_reason=s.get("finish_reason", "stop"),
                source_provider=s.get("source_provider", "azure_app_insights"),
                raw_attributes=s.get("raw_attributes", {}),
                tags=s.get("tags", {}),
            )
            session.add(rec)
            written += 1

        try:
            await session.commit()
            log.info("writer.spans_written", count=written)
        except Exception as exc:
            await session.rollback()
            log.error("writer.spans_commit_failed", error=str(exc))
            return 0

    return written


async def write_metrics(metrics: list[ConnectorMetric]) -> int:
    """
    Upsert ConnectorMetric records into daily_rollups.
    Returns the count of records written.
    """
    if not metrics:
        return 0

    written = 0
    async with get_analytics_session() as session:
        for m in metrics:
            try:
                await _upsert_daily_rollup(session, m)
                written += 1
            except Exception as exc:
                log.error(
                    "writer.upsert_failed",
                    source=m.source,
                    error=str(exc),
                )
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            log.error("writer.commit_failed", error=str(exc))
            return 0

    log.info("writer.metrics_done", written=written)
    return written


async def _upsert_daily_rollup(session: AsyncSession, m: ConnectorMetric) -> None:
    day = m.period_start.date()
    client_id = uuid.UUID(m.client_id)
    project_id = uuid.UUID(m.project_id) if m.project_id else None

    # Try to find existing rollup for this connector+day+model
    existing = await session.execute(
        select(DailyRollup).where(
            DailyRollup.client_id == client_id,
            DailyRollup.day == day,
            DailyRollup.model_name == (m.model_name or "unknown"),
        ).limit(1)
    )
    row = existing.scalar_one_or_none()

    if row:
        # Merge (add) new metrics to existing row
        row.total_calls = (row.total_calls or 0) + m.total_calls
        row.total_tokens = (row.total_tokens or 0) + m.total_tokens
        row.input_tokens = (row.input_tokens or 0) + m.input_tokens
        row.output_tokens = (row.output_tokens or 0) + m.output_tokens
        row.total_cost_usd = (row.total_cost_usd or 0.0) + m.cost_usd
        row.error_count = (row.error_count or 0) + m.failed_calls
        if m.avg_latency_ms is not None:
            row.avg_duration_ms = m.avg_latency_ms
    else:
        row = DailyRollup(
            client_id=client_id,
            project_id=project_id,
            day=day,
            model_name=m.model_name or "unknown",
            provider=m.provider,
            total_calls=m.total_calls,
            successful_calls=max(0, m.total_calls - m.failed_calls),
            total_tokens=m.total_tokens,
            input_tokens=m.input_tokens,
            output_tokens=m.output_tokens,
            total_cost_usd=m.cost_usd,
            error_count=m.failed_calls,
            failed_calls=m.failed_calls,
            avg_duration_ms=m.avg_latency_ms,
        )
        session.add(row)

    await session.flush()

