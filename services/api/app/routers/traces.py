"""
services/api/app/routers/traces.py
Trace-level drill-down endpoints.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user
from shared.db.session import analytics_session_dep
from shared.models.analytics_db import SpanRecord
from shared.models.schemas import PaginatedResponse, SpanDetail

from app.time_window import resolve_window

router = APIRouter()


@router.get(
    "/traces",
    response_model=PaginatedResponse,
    summary="List all traces across projects",
)
async def list_all_traces(
    period_days: int = Query(default=7, ge=1, le=366),
    start: datetime | None = Query(default=None, description="Window start (ISO-8601); overrides period_days"),
    end: datetime | None = Query(default=None, description="Window end (ISO-8601); defaults to now"),
    environment: str | None = Query(default=None),
    model_name: str | None = Query(default=None),
    success: bool | None = Query(default=None),
    connector_id: str | None = Query(default=None),
    source_provider: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None, description="Only spans from this project"),
    agent: str | None = Query(default=None, max_length=255, description="Only traces run by this agent (tags.agent or span name)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    from sqlalchemy import func
    window_start, window_end = resolve_window(period_days, start, end)

    q = select(SpanRecord).where(
        SpanRecord.timestamp >= window_start,
        SpanRecord.timestamp <= window_end,
    )
    if project_id:
        q = q.where(SpanRecord.project_id == project_id)
    if agent:
        # Whole traces (all their steps) in which this agent ran, not just the agent's own span.
        agent_traces = select(SpanRecord.trace_id).where(
            SpanRecord.span_kind == "agent",
            func.coalesce(SpanRecord.tags["agent"].astext, SpanRecord.span_name) == agent,
            SpanRecord.timestamp >= window_start,
            SpanRecord.timestamp <= window_end,
        )
        q = q.where(SpanRecord.trace_id.in_(agent_traces))
    if environment:
        q = q.where(SpanRecord.environment == environment)
    if model_name:
        q = q.where(SpanRecord.model_name == model_name)
    if success is not None:
        q = q.where(SpanRecord.success == success)
    if connector_id:
        if connector_id.lower() in ("sdk", "trustai_sdk", "direct_sdk"):
            q = q.where(SpanRecord.source_provider == "trustai_sdk")
        else:
            q = q.where(
                (SpanRecord.tags["connector_id"].astext == connector_id)
                | (SpanRecord.source_provider == connector_id)
            )
    elif source_provider:
        q = q.where(SpanRecord.source_provider == source_provider)

    count_q = select(func.count()).select_from(q.subquery())
    total_result = await session.execute(count_q)
    total = total_result.scalar_one()

    q = q.order_by(SpanRecord.timestamp.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    spans = result.scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_span_to_detail(s) for s in spans],
    )


@router.get(
    "/projects/{project_id}/traces",
    response_model=PaginatedResponse,
    summary="List traces for a project",
)
async def list_project_traces(
    project_id: uuid.UUID = Path(...),
    period_days: int = Query(default=1),
    environment: str | None = Query(default=None),
    model_name: str | None = Query(default=None),
    success: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)

    q = select(SpanRecord).where(
        SpanRecord.project_id == project_id,
        SpanRecord.timestamp >= start,
        SpanRecord.parent_span_id.is_(None),  # root spans only
    )
    if environment:
        q = q.where(SpanRecord.environment == environment)
    if model_name:
        q = q.where(SpanRecord.model_name == model_name)
    if success is not None:
        q = q.where(SpanRecord.success == success)

    from sqlalchemy import func
    count_q = select(func.count()).select_from(q.subquery())
    total_result = await session.execute(count_q)
    total = total_result.scalar_one()

    q = q.order_by(SpanRecord.timestamp.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    spans = result.scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_span_to_detail(s) for s in spans],
    )


@router.get(
    "/traces/{trace_id}",
    response_model=SpanDetail,
    summary="Get full trace waterfall for a single trace",
)
async def get_trace_waterfall(
    trace_id: str = Path(...),
    session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
) -> SpanDetail:
    result = await session.execute(
        select(SpanRecord).where(SpanRecord.trace_id == trace_id).order_by(SpanRecord.started_at)
    )
    spans = result.scalars().all()

    if not spans:
        raise HTTPException(status_code=404, detail="Trace not found")

    # Build tree
    by_span_id: dict[str, SpanDetail] = {}
    for s in spans:
        by_span_id[s.span_id] = _span_to_detail(s)

    roots: list[SpanDetail] = []
    for s in spans:
        detail = by_span_id[s.span_id]
        if s.parent_span_id and s.parent_span_id in by_span_id:
            by_span_id[s.parent_span_id].children.append(detail)
        else:
            roots.append(detail)

    return roots[0] if roots else _span_to_detail(spans[0])


def _span_to_detail(span: SpanRecord) -> SpanDetail:
    tags = span.tags or {}
    return SpanDetail(
        id=span.id,
        trace_id=span.trace_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        span_name=span.span_name,
        span_kind=span.span_kind,
        started_at=span.started_at,
        ended_at=span.ended_at,
        duration_ms=span.duration_ms,
        provider=span.provider,
        model_name=span.model_name,
        operation=span.operation,
        input_tokens=span.input_tokens,
        output_tokens=span.output_tokens,
        total_tokens=span.total_tokens,
        cost_usd=span.cost_usd,
        input_content=span.input_content,
        output_content=span.output_content,
        content_capture_mode=span.content_capture_mode,
        success=span.success,
        error_type=span.error_type,
        error_message=span.error_message,
        finish_reason=span.finish_reason,
        tags=tags,
        attributes=span.raw_attributes or {},
        client_id=span.client_id,
        project_id=span.project_id,
        source_provider=span.source_provider,
        connector_id=tags.get("connector_id"),
        connector_name=tags.get("connector_name"),
    )
