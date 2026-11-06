"""
services/governance/app/routers/evaluations.py
Red-team / classification evaluations and the prompt library.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_dep
from app.models import Evaluation, EvaluationStatus
from app.redteam.library import library_summary
from app.schemas import EvaluationCreate, EvaluationOut
from app.security import CurrentPrincipal
from app.services import evaluations as svc
from app.services.common import portal_url

router = APIRouter()
Session = Annotated[AsyncSession, Depends(session_dep)]


def _out(row: Evaluation, include_iterations: bool = False) -> EvaluationOut:
    """ORM -> API (iterations omitted unless requested; they can be large)."""
    out = EvaluationOut.model_validate(row, from_attributes=True)
    out.iterations = list(row.iterations or []) if include_iterations else None
    out.portal_url = portal_url(f"governance/evaluations/{row.id}")
    return out


@router.get("/redteam/library", summary="Red-team prompt library")
async def library() -> dict[str, Any]:
    """Attack categories, strategies and template counts."""
    return library_summary()


@router.post("/evaluations", response_model=EvaluationOut, status_code=status.HTTP_202_ACCEPTED, summary="Start an evaluation")
async def create(body: EvaluationCreate, principal: CurrentPrincipal, session: Session,
                 background: BackgroundTasks) -> EvaluationOut:
    """Queue a red-team run against the agent's endpoint; poll GET /evaluations/{id}."""
    row = await svc.create(session, principal, body)
    out = _out(row)
    await session.commit()  # the runner reads the row in its own session: it must be committed first
    background.add_task(svc.dispatch, row.id)
    return out


@router.get("/evaluations", response_model=list[EvaluationOut], summary="List evaluations")
async def list_all(principal: CurrentPrincipal, session: Session, agent_id: uuid.UUID | None = None,
                   status_filter: EvaluationStatus | None = Query(default=None, alias="status"),
                   limit: int = Query(default=50, ge=1, le=200)) -> list[EvaluationOut]:
    """Evaluations visible to the caller, newest first."""
    stmt = select(Evaluation).order_by(Evaluation.created_at.desc()).limit(limit)
    if principal.visible_projects() is not None:
        stmt = stmt.where(Evaluation.project_id.in_(principal.visible_projects()))
    if agent_id:
        stmt = stmt.where(Evaluation.agent_id == agent_id)
    if status_filter:
        stmt = stmt.where(Evaluation.status == status_filter)
    return [_out(r) for r in (await session.execute(stmt)).scalars()]


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationOut, summary="Get an evaluation")
async def get_one(evaluation_id: uuid.UUID, principal: CurrentPrincipal, session: Session,
                  include_iterations: bool = False) -> EvaluationOut:
    """Status, scores and summary; per-prompt iterations with include_iterations=true."""
    return _out(await svc.get_evaluation(session, principal, evaluation_id), include_iterations)


@router.post("/evaluations/{evaluation_id}/cancel", response_model=EvaluationOut, summary="Cancel an evaluation")
async def cancel(evaluation_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> EvaluationOut:
    """Stop a queued or running evaluation."""
    return _out(await svc.cancel(session, principal, evaluation_id))
