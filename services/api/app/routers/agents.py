"""
services/api/app/routers/agents.py
Agent-level analytics endpoints.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user
from shared.db.session import analytics_session_dep, metadata_session_dep
from shared.models.analytics_db import DailyRollup, SpanRecord
from shared.models.db import Agent, Client, Project
from shared.models.schemas import PaginatedResponse
from sqlalchemy import String, case, cast

from app.time_window import resolve_window

router = APIRouter()


@router.get("/agents", response_model=PaginatedResponse)
async def list_all_agents(
    period_days: int = Query(default=7, ge=1, le=366),
    start: datetime | None = Query(default=None, description="Window start (ISO-8601); overrides period_days"),
    end: datetime | None = Query(default=None, description="Window end (ISO-8601); defaults to now"),
    meta_session: AsyncSession = Depends(metadata_session_dep),
    analytics_session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    """
    Agents auto-discovered from telemetry, one row per (agent, project).

    SDK agent spans share a generic span name (e.g. ``agent.turn``); the business name of the
    agent travels in ``tags.agent``, so that is the grouping key when present.
    """
    window_start, window_end = resolve_window(period_days, start, end)
    agent_label = func.coalesce(SpanRecord.tags["agent"].astext, SpanRecord.span_name)

    agent_spans_q = (
        select(
            agent_label.label("name"),
            func.min(SpanRecord.span_name).label("span_name"),
            SpanRecord.project_id.label("project_id"),
            func.min(cast(SpanRecord.client_id, String)).label("client_id"),
            func.count(SpanRecord.id).label("total_calls"),
            func.sum(SpanRecord.total_tokens).label("total_tokens"),
            func.sum(SpanRecord.cost_usd).label("total_cost_usd"),
            func.avg(SpanRecord.duration_ms).label("avg_duration_ms"),
            func.sum(case((SpanRecord.success == False, 1), else_=0)).label("error_count"),  # noqa: E712
            func.max(SpanRecord.timestamp).label("last_active"),
        )
        .where(
            SpanRecord.span_kind == "agent",
            SpanRecord.timestamp >= window_start,
            SpanRecord.timestamp <= window_end,
        )
        .group_by(agent_label, SpanRecord.project_id)
        .order_by(func.count(SpanRecord.id).desc())
    )
    rows = (await analytics_session.execute(agent_spans_q)).all()

    # Resolve project and client display names from the metadata DB in one query.
    project_ids = {r.project_id for r in rows if r.project_id}
    names: dict[uuid.UUID, tuple[str, str | None]] = {}
    if project_ids:
        meta_rows = await meta_session.execute(
            select(Project.id, Project.name, Client.name)
            .join(Client, Client.id == Project.client_id, isouter=True)
            .where(Project.id.in_(project_ids))
        )
        names = {pid: (pname, cname) for pid, pname, cname in meta_rows.all()}

    items = []
    for r in rows:
        total_calls = r.total_calls or 0
        err_count = r.error_count or 0
        project_name, client_name = names.get(r.project_id, (None, None))
        items.append({
            # Unique per row: the same agent name can run in several projects.
            "id": f"{r.project_id or 'none'}::{r.name}",
            "name": r.name,
            "slug": r.name.lower().replace("_", "-").replace(" ", "-"),
            "span_name": r.span_name,
            "project_id": str(r.project_id) if r.project_id else None,
            "project_name": project_name,
            "client_id": r.client_id,
            "client_name": client_name,
            "agent_type": "autonomous",
            "total_calls": total_calls,
            "total_tokens": int(r.total_tokens or 0),
            "total_cost_usd": float(r.total_cost_usd or 0),
            "error_rate": round(err_count / total_calls, 4) if total_calls > 0 else 0.0,
            "avg_duration_ms": round(float(r.avg_duration_ms), 1) if r.avg_duration_ms else 0.0,
            "last_active": r.last_active.isoformat() if r.last_active else None,
        })

    return PaginatedResponse(total=len(items), page=1, page_size=max(len(items), 1), items=items)


@router.get("/projects/{project_id}/agents", response_model=PaginatedResponse)
async def list_project_agents(
    project_id: uuid.UUID = Path(...),
    period_days: int = Query(default=7),
    meta_session: AsyncSession = Depends(metadata_session_dep),
    analytics_session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    result = await meta_session.execute(
        select(Agent).where(Agent.project_id == project_id).order_by(Agent.name)
    )
    agents = result.scalars().all()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)
    agent_ids = [a.id for a in agents]

    summaries = await _get_agent_summaries(analytics_session, agent_ids, start, now)

    items = [
        {
            "id": str(a.id),
            "name": a.name,
            "slug": a.slug,
            "project_id": str(a.project_id),
            "agent_type": a.agent_type,
            "total_cost_usd": summaries.get(a.id, {}).get("total_cost_usd", 0),
            "total_calls": summaries.get(a.id, {}).get("total_calls", 0),
            "error_rate": summaries.get(a.id, {}).get("error_rate", 0),
            "avg_duration_ms": summaries.get(a.id, {}).get("avg_duration_ms"),
        }
        for a in agents
    ]
    return PaginatedResponse(total=len(agents), page=1, page_size=len(agents), items=items)


async def _get_agent_summaries(session, agent_ids, start, end):
    if not agent_ids:
        return {}
    result = await session.execute(
        select(
            DailyRollup.agent_id,
            func.sum(DailyRollup.total_cost_usd).label("total_cost_usd"),
            func.sum(DailyRollup.total_calls).label("total_calls"),
            func.sum(DailyRollup.failed_calls).label("failed_calls"),
            func.avg(DailyRollup.avg_duration_ms).label("avg_duration_ms"),
        )
        .where(DailyRollup.agent_id.in_(agent_ids), DailyRollup.day >= start, DailyRollup.day < end)
        .group_by(DailyRollup.agent_id)
    )
    return {
        row.agent_id: {
            "total_cost_usd": float(row.total_cost_usd or 0),
            "total_calls": int(row.total_calls or 0),
            "error_rate": round(float(row.failed_calls or 0) / max(int(row.total_calls or 1), 1) * 100, 2),
            "avg_duration_ms": float(row.avg_duration_ms or 0),
        }
        for row in result
    }
