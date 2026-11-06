"""
services/api/app/routers/projects.py
Project-level analytics endpoints.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user
from shared.db.session import analytics_session_dep, metadata_session_dep
from shared.models.analytics_db import DailyRollup, SpanRecord
from shared.models.db import Agent, Project
from shared.models.schemas import PaginatedResponse, ProjectResponse

router = APIRouter()


@router.get("/projects", response_model=PaginatedResponse)
async def list_all_projects(
    period_days: int = Query(default=7),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    meta_session: AsyncSession = Depends(metadata_session_dep),
    analytics_session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    offset = (page - 1) * page_size
    result = await meta_session.execute(
        select(Project)
        .where(Project.is_active == True)
        .order_by(Project.name)
        .offset(offset)
        .limit(page_size)
    )
    projects = result.scalars().all()

    count_result = await meta_session.execute(
        select(func.count(Project.id)).where(Project.is_active == True)
    )
    total = count_result.scalar_one()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)
    project_ids = [p.id for p in projects]

    summaries = await _get_project_summaries(analytics_session, project_ids, start, now)

    items = [
        ProjectResponse(
            id=p.id,
            client_id=p.client_id,
            name=p.name,
            slug=p.slug,
            description=p.description,
            content_capture_mode=p.content_capture_mode,
            content_capture_overrides=p.content_capture_overrides,
            is_active=p.is_active,
            monthly_budget_usd=p.monthly_budget_usd,
            tags=p.tags,
            created_at=p.created_at,
            total_cost_usd=summaries.get(p.id, {}).get("total_cost_usd"),
            total_calls=summaries.get(p.id, {}).get("total_calls"),
            error_rate=summaries.get(p.id, {}).get("error_rate"),
        )
        for p in projects
    ]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/clients/{client_id}/projects", response_model=PaginatedResponse)
async def list_client_projects(
    client_id: uuid.UUID = Path(...),
    period_days: int = Query(default=7),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    meta_session: AsyncSession = Depends(metadata_session_dep),
    analytics_session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    offset = (page - 1) * page_size
    result = await meta_session.execute(
        select(Project)
        .where(Project.client_id == client_id, Project.is_active == True)
        .order_by(Project.name)
        .offset(offset)
        .limit(page_size)
    )
    projects = result.scalars().all()

    count_result = await meta_session.execute(
        select(func.count(Project.id)).where(Project.client_id == client_id, Project.is_active == True)
    )
    total = count_result.scalar_one()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)
    project_ids = [p.id for p in projects]

    summaries = await _get_project_summaries(analytics_session, project_ids, start, now)

    items = [
        ProjectResponse(
            id=p.id,
            client_id=p.client_id,
            name=p.name,
            slug=p.slug,
            description=p.description,
            content_capture_mode=p.content_capture_mode,
            content_capture_overrides=p.content_capture_overrides,
            is_active=p.is_active,
            monthly_budget_usd=p.monthly_budget_usd,
            tags=p.tags,
            created_at=p.created_at,
            total_cost_usd=summaries.get(p.id, {}).get("total_cost_usd"),
            total_calls=summaries.get(p.id, {}).get("total_calls"),
        )
        for p in projects
    ]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID = Path(...),
    period_days: int = Query(default=7),
    meta_session: AsyncSession = Depends(metadata_session_dep),
    analytics_session: AsyncSession = Depends(analytics_session_dep),
    current_user=Depends(get_current_user),
):
    result = await meta_session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)
    summaries = await _get_project_summaries(analytics_session, [project_id], start, now)
    summary = summaries.get(project_id, {})

    return ProjectResponse(
        id=project.id,
        client_id=project.client_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        content_capture_mode=project.content_capture_mode,
        content_capture_overrides=project.content_capture_overrides,
        is_active=project.is_active,
        monthly_budget_usd=project.monthly_budget_usd,
        tags=project.tags,
        created_at=project.created_at,
        total_cost_usd=summary.get("total_cost_usd"),
        total_calls=summary.get("total_calls"),
    )


async def _get_project_summaries(session, project_ids, start, end):
    if not project_ids:
        return {}
    result = await session.execute(
        select(
            DailyRollup.project_id,
            func.sum(DailyRollup.total_cost_usd).label("total_cost_usd"),
            func.sum(DailyRollup.total_calls).label("total_calls"),
        )
        .where(DailyRollup.project_id.in_(project_ids), DailyRollup.day >= start, DailyRollup.day < end)
        .group_by(DailyRollup.project_id)
    )
    return {
        row.project_id: {"total_cost_usd": float(row.total_cost_usd or 0), "total_calls": int(row.total_calls or 0)}
        for row in result
    }
