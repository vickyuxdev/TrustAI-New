"""
services/governance/app/services/common.py
Helpers shared by every governance service: agent lookup with access checks, slugs, portal deep links, events.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GovernanceEvent, GovernedAgent
from app.security import Principal


def slugify(value: str, max_len: int = 120) -> str:
    """Lower-case, dash-separated identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "agent")[:max_len]


def portal_url(path: str) -> str:
    """Absolute TrustAI dashboard link."""
    return f"{get_settings().portal_url.rstrip('/')}/{path.lstrip('/')}"


async def emit(session: AsyncSession, *, project_id: uuid.UUID, event_type: str, resource_type: str,
               resource_id: str | uuid.UUID, actor: str, agent_id: uuid.UUID | None = None,
               severity: str = "info", payload: dict[str, Any] | None = None) -> GovernanceEvent:
    """Append a governance event (audit trail + alert feed)."""
    event = GovernanceEvent(project_id=project_id, event_type=event_type, severity=severity,
                            resource_type=resource_type, resource_id=str(resource_id), agent_id=agent_id,
                            actor=actor, payload=payload or {})
    session.add(event)
    return event


async def get_agent(session: AsyncSession, principal: Principal, agent_id: uuid.UUID | None = None,
                    external_id: str | None = None) -> GovernedAgent:
    """Load an agent by id or external id, enforcing project access (404 when invisible)."""
    if agent_id is None and not external_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "agent_id or external_id is required")
    stmt = select(GovernedAgent)
    if agent_id is not None:
        stmt = stmt.where(GovernedAgent.id == agent_id)
    else:
        stmt = stmt.where(GovernedAgent.external_id == external_id)
        if principal.bound_project is not None:
            stmt = stmt.where(GovernedAgent.project_id == principal.bound_project)
    visible = principal.visible_projects()
    if visible is not None:
        stmt = stmt.where(GovernedAgent.project_id.in_(visible))
    agents = (await session.execute(stmt.limit(2))).scalars().all()
    if not agents:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    if len(agents) > 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "external_id is ambiguous across projects; pass agent_id")
    return agents[0]


async def paginate(session: AsyncSession, stmt: Select[Any], limit: int, offset: int) -> tuple[list[Any], int]:
    """Run a select with limit/offset and return (rows, total)."""
    total = (await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return list(rows), int(total)
