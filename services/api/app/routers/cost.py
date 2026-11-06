"""
services/api/app/routers/cost.py
Cost intelligence endpoints — breakdown by model, client, project, provider, environment.
"""
from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user
from shared.db.session import analytics_session_dep
from shared.models.analytics_db import DailyRollup
from shared.models.schemas import CostBreakdown

from app.time_window import day_floor, resolve_window

router = APIRouter()


@router.get(
    "/cost/breakdown",
    response_model=CostBreakdown,
    summary="Cost breakdown across all dimensions",
)
async def get_cost_breakdown(
    period_days: int = Query(default=30, ge=1, le=365),
    start: Optional[datetime] = Query(default=None, description="Window start (ISO-8601); overrides period_days"),
    end: Optional[datetime] = Query(default=None, description="Window end (ISO-8601); defaults to now"),
    client_id: Optional[uuid.UUID] = Query(default=None, description="Filter by client UUID"),
    project_id: Optional[uuid.UUID] = Query(default=None, description="Filter by project UUID"),
    environment: Optional[str] = Query(default=None, description="Filter by environment (production/staging/development)"),
    session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
) -> CostBreakdown:
    window_start, window_end = resolve_window(period_days, start, end)

    # Build base filters — rollups are daily rows keyed at midnight, so include the start day.
    base_filters = [DailyRollup.day >= day_floor(window_start), DailyRollup.day < window_end]
    if client_id:
        base_filters.append(DailyRollup.client_id == client_id)
    if project_id:
        base_filters.append(DailyRollup.project_id == project_id)
    if environment:
        base_filters.append(DailyRollup.environment == environment)

    by_client = await _breakdown_by(session, DailyRollup.client_id, base_filters)
    by_project = await _breakdown_by(session, DailyRollup.project_id, base_filters)
    by_model = await _breakdown_by(session, DailyRollup.model_name, base_filters)
    by_provider = await _breakdown_by(session, DailyRollup.provider, base_filters)
    by_environment = await _breakdown_by(session, DailyRollup.environment, base_filters)
    by_agent = await _breakdown_by(session, DailyRollup.agent_id, base_filters)
    time_series = await _cost_time_series(session, base_filters)
    top_projects = await _top_projects(session, base_filters)

    return CostBreakdown(
        by_client=by_client,
        by_project=by_project,
        by_model=by_model,
        by_provider=by_provider,
        by_environment=by_environment,
        by_agent=by_agent,
        time_series=time_series,
        top_projects=top_projects,
    )


async def _breakdown_by(
    session: AsyncSession,
    group_col,
    base_filters: list,
) -> list[dict]:
    result = await session.execute(
        select(
            group_col.label("dimension"),
            func.sum(DailyRollup.total_cost_usd).label("total_cost_usd"),
            func.sum(DailyRollup.total_calls).label("total_calls"),
            func.sum(DailyRollup.total_tokens).label("total_tokens"),
            func.sum(DailyRollup.total_input_tokens).label("total_input_tokens"),
            func.sum(DailyRollup.total_output_tokens).label("total_output_tokens"),
        )
        .where(*base_filters)
        .group_by(group_col)
        .order_by(func.sum(DailyRollup.total_cost_usd).desc())
        .limit(50)
    )
    return [
        {
            "dimension": str(row.dimension),
            "total_cost_usd": round(float(row.total_cost_usd or 0), 4),
            "total_calls": int(row.total_calls or 0),
            "total_tokens": int(row.total_tokens or 0),
            "total_input_tokens": int(row.total_input_tokens or 0),
            "total_output_tokens": int(row.total_output_tokens or 0),
        }
        for row in result
    ]


async def _cost_time_series(
    session: AsyncSession,
    base_filters: list,
) -> list[dict]:
    result = await session.execute(
        select(
            DailyRollup.day,
            func.sum(DailyRollup.total_cost_usd).label("total_cost_usd"),
            func.sum(DailyRollup.total_calls).label("total_calls"),
            func.sum(DailyRollup.total_tokens).label("total_tokens"),
        )
        .where(*base_filters)
        .group_by(DailyRollup.day)
        .order_by(DailyRollup.day)
    )
    return [
        {
            "date": row.day.isoformat(),
            "total_cost_usd": round(float(row.total_cost_usd or 0), 4),
            "total_calls": int(row.total_calls or 0),
            "total_tokens": int(row.total_tokens or 0),
        }
        for row in result
    ]


async def _top_projects(
    session: AsyncSession,
    base_filters: list,
) -> list[dict]:
    result = await session.execute(
        select(
            DailyRollup.project_id,
            func.sum(DailyRollup.total_cost_usd).label("total_cost_usd"),
            func.sum(DailyRollup.total_calls).label("total_calls"),
            func.sum(DailyRollup.total_tokens).label("total_tokens"),
            func.sum(DailyRollup.failed_calls).label("failed_calls"),
        )
        .where(*base_filters)
        .group_by(DailyRollup.project_id)
        .order_by(func.sum(DailyRollup.total_cost_usd).desc())
        .limit(10)
    )
    rows = result.all()
    return [
        {
            "dimension": str(row.project_id),
            "name": str(row.project_id),
            "total_cost_usd": round(float(row.total_cost_usd or 0), 4),
            "total_calls": int(row.total_calls or 0),
            "total_tokens": int(row.total_tokens or 0),
            "error_rate": round(
                float(row.failed_calls or 0) / max(int(row.total_calls or 1), 1) * 100, 2
            ),
        }
        for row in rows
    ]
