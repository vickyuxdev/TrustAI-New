"""
services/governance/app/routers/risk.py
Risk assessment: templates, draft/answers/validate/submit/classify, the human decision, and a one-shot endpoint
for automation (create + pre-fill from facts + submit + classify).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_dep
from app.models import RiskAssessment
from app.schemas import AnswersIn, AssessmentCreate, AssessmentOut, DecisionIn, RiskAssessIn
from app.security import CurrentPrincipal, require_human
from app.services import risk as svc
from app.services.common import portal_url

router = APIRouter()
Session = Annotated[AsyncSession, Depends(session_dep)]


def _out(row: RiskAssessment) -> AssessmentOut:
    """ORM -> API with the portal deep link."""
    out = AssessmentOut.model_validate(row)
    out.portal_url = portal_url(f"governance/risk/{row.id}")
    return out


@router.get("/risk/templates", summary="Risk templates")
async def templates() -> list[dict[str, Any]]:
    """Available assessment templates."""
    return [svc.template()]


@router.get("/risk/templates/{template_id}", summary="Risk template")
async def template(template_id: str) -> dict[str, Any]:
    """Template with sections, questions, options, points and tier controls."""
    if template_id != svc.TEMPLATE_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    return svc.template()


@router.post("/risk/assess", response_model=AssessmentOut, status_code=status.HTTP_201_CREATED,
             summary="One-shot assessment from build facts")
async def assess(body: RiskAssessIn, principal: CurrentPrincipal, session: Session) -> AssessmentOut:
    """Create, pre-fill from facts, submit (conservative defaults recorded as assumptions) and classify."""
    row = await svc.create(session, principal, body.agent_id, body.external_id, body.answers, body.facts, body.template_id)
    row = await svc.submit(session, principal, row, fill_defaults=True)
    return _out(row)


@router.post("/assessments", response_model=AssessmentOut, status_code=status.HTTP_201_CREATED, summary="Start an assessment")
async def create(body: AssessmentCreate, principal: CurrentPrincipal, session: Session) -> AssessmentOut:
    """Draft assessment, optionally pre-filled from facts."""
    row = await svc.create(session, principal, body.agent_id, None, body.answers, body.facts, body.template_id)
    row.validation = svc.validate(row.answers)
    return _out(row)


@router.get("/assessments", response_model=list[AssessmentOut], summary="List assessments")
async def list_all(principal: CurrentPrincipal, session: Session, agent_id: uuid.UUID | None = None,
                   status_filter: str | None = Query(default=None, alias="status"),
                   limit: int = Query(default=100, ge=1, le=500)) -> list[AssessmentOut]:
    """Assessments visible to the caller, newest first."""
    stmt = select(RiskAssessment).order_by(RiskAssessment.created_at.desc()).limit(limit)
    if principal.visible_projects() is not None:
        stmt = stmt.where(RiskAssessment.project_id.in_(principal.visible_projects()))
    if agent_id:
        stmt = stmt.where(RiskAssessment.agent_id == agent_id)
    if status_filter:
        stmt = stmt.where(RiskAssessment.status == status_filter)
    return [_out(r) for r in (await session.execute(stmt)).scalars()]


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut, summary="Get an assessment")
async def get_one(assessment_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> AssessmentOut:
    """One assessment with answers, tier reasons and decision."""
    return _out(await svc.get_assessment(session, principal, assessment_id))


@router.put("/assessments/{assessment_id}/answers", response_model=AssessmentOut, summary="Save answers")
async def answers(assessment_id: uuid.UUID, body: AnswersIn, principal: CurrentPrincipal, session: Session) -> AssessmentOut:
    """Merge answers (returns the assessment to draft if it was classified)."""
    row = await svc.get_assessment(session, principal, assessment_id)
    return _out(await svc.save_answers(session, principal, row, body.answers, body.evidence))


@router.post("/assessments/{assessment_id}/validate", summary="Validate answers")
async def validate(assessment_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> dict[str, Any]:
    """Missing required answers and invalid values."""
    row = await svc.get_assessment(session, principal, assessment_id)
    row.validation = svc.validate(row.answers or {})
    return row.validation


@router.post("/assessments/{assessment_id}/submit", response_model=AssessmentOut, summary="Submit and classify")
async def submit(assessment_id: uuid.UUID, principal: CurrentPrincipal, session: Session,
                 fill_defaults: bool = False) -> AssessmentOut:
    """Submit (422 if incomplete unless fill_defaults) and classify into a tier."""
    row = await svc.get_assessment(session, principal, assessment_id)
    return _out(await svc.submit(session, principal, row, fill_defaults=fill_defaults))


@router.post("/assessments/{assessment_id}/classify", response_model=AssessmentOut, summary="Re-run classification")
async def classify(assessment_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> AssessmentOut:
    """Re-classify a submitted assessment (after template changes)."""
    row = await svc.get_assessment(session, principal, assessment_id)
    return _out(await svc.run_classification(session, principal, row))


@router.post("/assessments/{assessment_id}/decision", response_model=AssessmentOut, summary="Record the human decision")
async def decision(assessment_id: uuid.UUID, body: DecisionIn, principal: CurrentPrincipal, session: Session) -> AssessmentOut:
    """Approve, approve with conditions or reject - people only, never machine keys."""
    require_human(principal)
    row = await svc.get_assessment(session, principal, assessment_id)
    return _out(await svc.decide(session, principal, row, body.decision, body.conditions, body.note))
