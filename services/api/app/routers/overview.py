"""
services/api/app/routers/overview.py
GET /api/v1/overview — company-wide KPI summary for the executive dashboard.
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user
from shared.db.session import analytics_session_dep
from shared.models.analytics_db import DailyRollup, HourlyRollup
from shared.models.schemas import OverviewMetrics

from app.time_window import day_floor, resolve_window

router = APIRouter()


@router.get(
    "/overview",
    response_model=OverviewMetrics,
    summary="Company-wide KPI overview",
)
async def get_overview(
    period_days: int = Query(default=7, ge=1, le=90, description="Look-back window in days"),
    start: datetime | None = Query(default=None, description="Window start (ISO-8601); overrides period_days"),
    end: datetime | None = Query(default=None, description="Window end (ISO-8601); defaults to now"),
    session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
) -> OverviewMetrics:
    period_start, period_end = resolve_window(period_days, start, end)
    # The comparison period is the same length, immediately before the selected one.
    prev_start = period_start - (period_end - period_start)

    # Rollups are daily rows keyed at midnight, so align their bounds to whole days.
    current = await _aggregate_rollups(session, day_floor(period_start), period_end)
    previous = await _aggregate_rollups(session, day_floor(prev_start), day_floor(period_start))

    def _pct_change(current_val: float, prev_val: float) -> float:
        if not prev_val:
            return 0.0
        return round(((current_val - prev_val) / prev_val) * 100, 1)

    # Unique active projects and agents from span records
    active_counts = await _get_active_entity_counts(session, period_start, period_end)

    return OverviewMetrics(
        period_start=period_start,
        period_end=period_end,
        total_cost_usd=current.get("total_cost_usd", 0.0),
        total_calls=current.get("total_calls", 0),
        total_tokens=current.get("total_tokens", 0),
        total_input_tokens=current.get("total_input_tokens", 0),
        total_output_tokens=current.get("total_output_tokens", 0),
        error_rate=_error_rate(current),
        avg_latency_ms=current.get("avg_duration_ms", 0.0),
        p95_latency_ms=current.get("p95_duration_ms", 0.0),
        active_projects=active_counts.get("projects", 0),
        active_agents=active_counts.get("agents", 0),
        cost_trend_pct=_pct_change(current.get("total_cost_usd", 0), previous.get("total_cost_usd", 0)),
        calls_trend_pct=_pct_change(current.get("total_calls", 0), previous.get("total_calls", 0)),
    )


async def _aggregate_rollups(
    session: AsyncSession,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    result = await session.execute(
        select(
            func.sum(DailyRollup.total_calls).label("total_calls"),
            func.sum(DailyRollup.successful_calls).label("successful_calls"),
            func.sum(DailyRollup.failed_calls).label("failed_calls"),
            func.sum(DailyRollup.total_input_tokens).label("total_input_tokens"),
            func.sum(DailyRollup.total_output_tokens).label("total_output_tokens"),
            func.sum(DailyRollup.total_tokens).label("total_tokens"),
            func.sum(DailyRollup.total_cost_usd).label("total_cost_usd"),
            func.avg(DailyRollup.avg_duration_ms).label("avg_duration_ms"),
            func.avg(DailyRollup.p95_duration_ms).label("p95_duration_ms"),
        ).where(DailyRollup.day >= start, DailyRollup.day < end)
    )
    row = result.one_or_none()
    if not row:
        return {}
    return {k: (float(v) if v is not None else 0.0) for k, v in row._mapping.items()}


async def _get_active_entity_counts(
    session: AsyncSession,
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    from shared.models.analytics_db import SpanRecord
    result = await session.execute(
        select(
            func.count(func.distinct(SpanRecord.project_id)).label("projects"),
            func.count(func.distinct(SpanRecord.agent_id)).label("agents"),
        ).where(SpanRecord.timestamp >= start, SpanRecord.timestamp < end)
    )
    row = result.one_or_none()
    if not row:
        return {"projects": 0, "agents": 0}
    return {"projects": int(row.projects or 0), "agents": int(row.agents or 0)}


def _error_rate(agg: dict[str, Any]) -> float:
    total = agg.get("total_calls", 0)
    if not total:
        return 0.0
    failed = agg.get("failed_calls", 0)
    return round((failed / total) * 100, 2)
