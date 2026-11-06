"""
services/api/app/routers/clients.py
Client-level analytics endpoints.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user, require_client_access
from shared.db.session import analytics_session_dep, metadata_session_dep
from shared.models.analytics_db import DailyRollup, SpanRecord
from shared.models.db import Client, Project, UserRole
from shared.models.schemas import ClientResponse, PaginatedResponse

router = APIRouter()


@router.get(
    "/clients",
    response_model=PaginatedResponse,
    summary="List all clients with summary metrics",
)
async def list_clients(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    period_days: int = Query(default=7, ge=1, le=90),
    meta_session: AsyncSession = Depends(metadata_session_dep),
    analytics_session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    # Filter to clients the user can see
    offset = (page - 1) * page_size
    clients_result = await meta_session.execute(
        select(Client)
        .where(Client.is_active == True)
        .order_by(Client.name)
        .offset(offset)
        .limit(page_size)
    )
    clients = clients_result.scalars().all()

    count_result = await meta_session.execute(
        select(func.count(Client.id)).where(Client.is_active == True)
    )
    total = count_result.scalar_one()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)

    # Batch-fetch analytics summaries per client
    client_ids = [c.id for c in clients]
    summaries = await _get_client_summaries(analytics_session, client_ids, start, now)
    project_counts = await _get_project_counts(meta_session, client_ids)

    items = []
    for c in clients:
        summary = summaries.get(c.id, {})
        resp = ClientResponse(
            id=c.id,
            name=c.name,
            slug=c.slug,
            client_type=c.client_type,
            description=c.description,
            is_active=c.is_active,
            monthly_budget_usd=c.monthly_budget_usd,
            created_at=c.created_at,
            total_cost_usd=summary.get("total_cost_usd"),
            total_calls=summary.get("total_calls"),
            active_projects=project_counts.get(c.id, 0),
        )
        items.append(resp)

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get(
    "/clients/{client_id}",
    response_model=ClientResponse,
    summary="Get a single client with metrics",
)
async def get_client(
    client_id: uuid.UUID = Path(...),
    period_days: int = Query(default=7),
    meta_session: AsyncSession = Depends(metadata_session_dep),
    analytics_session: AsyncSession = Depends(analytics_session_dep),
    _=require_client_access(min_role=UserRole.PROJECT_VIEWER),
):
    result = await meta_session.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Client not found")

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)
    summaries = await _get_client_summaries(analytics_session, [client_id], start, now)
    summary = summaries.get(client_id, {})
    project_counts = await _get_project_counts(meta_session, [client_id])

    return ClientResponse(
        id=client.id,
        name=client.name,
        slug=client.slug,
        client_type=client.client_type,
        description=client.description,
        is_active=client.is_active,
        monthly_budget_usd=client.monthly_budget_usd,
        created_at=client.created_at,
        total_cost_usd=summary.get("total_cost_usd"),
        total_calls=summary.get("total_calls"),
        active_projects=project_counts.get(client_id, 0),
    )


async def _get_client_summaries(
    session: AsyncSession,
    client_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
) -> dict[uuid.UUID, dict]:
    if not client_ids:
        return {}
    result = await session.execute(
        select(
            DailyRollup.client_id,
            func.sum(DailyRollup.total_cost_usd).label("total_cost_usd"),
            func.sum(DailyRollup.total_calls).label("total_calls"),
        )
        .where(
            DailyRollup.client_id.in_(client_ids),
            DailyRollup.day >= start,
            DailyRollup.day < end,
        )
        .group_by(DailyRollup.client_id)
    )
    return {
        row.client_id: {"total_cost_usd": float(row.total_cost_usd or 0), "total_calls": int(row.total_calls or 0)}
        for row in result
    }


async def _get_project_counts(
    session: AsyncSession,
    client_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not client_ids:
        return {}
    result = await session.execute(
        select(Project.client_id, func.count(Project.id).label("count"))
        .where(Project.client_id.in_(client_ids), Project.is_active == True)
        .group_by(Project.client_id)
    )
    return {row.client_id: int(row.count) for row in result}
