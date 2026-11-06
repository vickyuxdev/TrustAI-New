"""
services/governance/app/routers/guardrails.py
Guardrails (CRUD, evaluate, history), policies (CRUD, recommend, enforce) and stand-alone metrics.
System catalog rows are read-only; project rows are editable by callers with access to the project.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_dep
from app.engine.base import EvalContext
from app.engine.pii import find_pii, redact
from app.engine.registry import EVALUATOR_CATALOG, EVALUATORS, run_guardrail
from app.models import Guardrail, GuardrailEvaluation, Policy
from app.schemas import (
    EnforceIn,
    EnforceOut,
    GuardrailEvaluateIn,
    GuardrailEvaluateOut,
    GuardrailEvaluationOut,
    GuardrailIn,
    GuardrailOut,
    GuardrailUpdate,
    MetricIn,
    PolicyIn,
    PolicyOut,
    PolicyUpdate,
    RecommendIn,
    Recommendation,
)
from app.security import CurrentPrincipal, Principal
from app.services import enforcement
from app.services.common import emit
from app.services.evidence import list_guardrails_for

router = APIRouter()
Session = Annotated[AsyncSession, Depends(session_dep)]


def _check_editable(row: Guardrail | Policy, principal: Principal) -> None:
    """System catalog rows are immutable; project rows need project access."""
    if row.is_system or row.project_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "system catalog entries are read-only; copy it into your project")
    principal.require_project(row.project_id)


def _check_evaluators(specs: list[Any]) -> None:
    """Reject unknown evaluator types up front."""
    unknown = sorted({s.type for s in specs} - set(EVALUATORS))
    if unknown:
        raise HTTPException(422, f"unknown evaluator types: {unknown}")


# --------------------------------------------------------------------------------------------- guardrails


@router.get("/guardrails/catalog", summary="Available evaluators")
async def evaluator_catalog() -> list[dict[str, Any]]:
    """Every evaluator type with its parameters and backends."""
    return EVALUATOR_CATALOG


@router.get("/guardrails", response_model=list[GuardrailOut], summary="List guardrails")
async def list_guardrails(principal: CurrentPrincipal, session: Session) -> list[Any]:
    """System guardrails and those of the caller's projects."""
    return await list_guardrails_for(session, principal)


@router.post("/guardrails", response_model=GuardrailOut, status_code=status.HTTP_201_CREATED, summary="Create a guardrail")
async def create_guardrail(body: GuardrailIn, principal: CurrentPrincipal, session: Session) -> Guardrail:
    """Project guardrail from evaluator specs."""
    _check_evaluators(body.evaluators)
    project_id = principal.resolve_project(body.project_id)
    row = Guardrail(project_id=project_id, key=body.key, name=body.name, description=body.description,
                    evaluators=[e.model_dump() for e in body.evaluators], tags=body.tags)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"guardrail key {body.key!r} already exists") from exc
    await emit(session, project_id=project_id, event_type="guardrail.created", resource_type="guardrail",
               resource_id=row.id, actor=principal.subject)
    return row


@router.get("/guardrails/{guardrail_id}", response_model=GuardrailOut, summary="Get a guardrail")
async def get_guardrail(guardrail_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> Guardrail:
    """One guardrail definition."""
    return await enforcement.get_guardrail(session, principal, guardrail_id)


@router.patch("/guardrails/{guardrail_id}", response_model=GuardrailOut, summary="Update a guardrail")
async def update_guardrail(guardrail_id: uuid.UUID, body: GuardrailUpdate, principal: CurrentPrincipal,
                           session: Session) -> Guardrail:
    """Edit a project guardrail (version is bumped when evaluators change)."""
    row = await enforcement.get_guardrail(session, principal, guardrail_id)
    _check_editable(row, principal)
    if body.evaluators is not None:
        _check_evaluators(body.evaluators)
        row.evaluators = [e.model_dump() for e in body.evaluators]
        row.version += 1
    for field in ("name", "description", "tags"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    await emit(session, project_id=row.project_id, event_type="guardrail.updated", resource_type="guardrail",
               resource_id=row.id, actor=principal.subject, payload={"version": row.version})
    return row


@router.delete("/guardrails/{guardrail_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a guardrail")
async def delete_guardrail(guardrail_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> Response:
    """Delete a project guardrail that no policy references."""
    row = await enforcement.get_guardrail(session, principal, guardrail_id)
    _check_editable(row, principal)
    for p in (await session.execute(select(Policy))).scalars():
        if any(str(r.get("guardrail_id")) == str(row.id) for r in p.rules or []):
            raise HTTPException(status.HTTP_409_CONFLICT, f"guardrail is used by policy {p.name!r}")
    await session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/guardrails/{guardrail_id}/evaluate", response_model=GuardrailEvaluateOut, summary="Evaluate text")
async def evaluate(guardrail_id: uuid.UUID, body: GuardrailEvaluateIn, principal: CurrentPrincipal,
                   session: Session) -> GuardrailEvaluateOut:
    """Score text against one guardrail; the decision is stored (hash only)."""
    return await enforcement.evaluate_guardrail(session, principal, guardrail_id, body)


@router.get("/guardrails/{guardrail_id}/evaluations", response_model=list[GuardrailEvaluationOut],
            summary="Guardrail decision history")
async def evaluations(guardrail_id: uuid.UUID, principal: CurrentPrincipal, session: Session,
                      agent_id: uuid.UUID | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[Any]:
    """Latest decisions of a guardrail, optionally for one agent."""
    await enforcement.get_guardrail(session, principal, guardrail_id)
    stmt = select(GuardrailEvaluation).where(GuardrailEvaluation.guardrail_id == guardrail_id)
    if principal.visible_projects() is not None:
        stmt = stmt.where(GuardrailEvaluation.project_id.in_(principal.visible_projects()))
    if agent_id:
        stmt = stmt.where(GuardrailEvaluation.agent_id == agent_id)
    return list((await session.execute(stmt.order_by(GuardrailEvaluation.created_at.desc()).limit(limit))).scalars())


@router.get("/guardrail-evaluations", response_model=list[GuardrailEvaluationOut], summary="Recent guardrail decisions")
async def recent_evaluations(principal: CurrentPrincipal, session: Session, agent_id: uuid.UUID | None = None,
                             passed: bool | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[Any]:
    """Latest decisions across guardrails (runtime, gateway, API, evaluation)."""
    stmt = select(GuardrailEvaluation)
    if principal.visible_projects() is not None:
        stmt = stmt.where(GuardrailEvaluation.project_id.in_(principal.visible_projects()))
    if agent_id:
        stmt = stmt.where(GuardrailEvaluation.agent_id == agent_id)
    if passed is not None:
        stmt = stmt.where(GuardrailEvaluation.passed.is_(passed))
    return list((await session.execute(stmt.order_by(GuardrailEvaluation.created_at.desc()).limit(limit))).scalars())


# --------------------------------------------------------------------------------------------- policies


@router.get("/policies", response_model=list[PolicyOut], summary="List policies")
async def list_policies(principal: CurrentPrincipal, session: Session,
                        search: str | None = Query(default=None, max_length=200),
                        tags: list[str] = Query(default=[])) -> list[Any]:
    """System and project policies, filterable by text and tags."""
    stmt = select(Policy)
    if principal.visible_projects() is not None:
        stmt = stmt.where(or_(Policy.project_id.is_(None), Policy.project_id.in_(principal.visible_projects())))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(Policy.name.ilike(like), Policy.key.ilike(like), Policy.description.ilike(like)))
    rows = list((await session.execute(stmt.order_by(Policy.is_system.desc(), Policy.name))).scalars())
    if tags:
        wanted = {t.lower() for t in tags}
        rows = [p for p in rows if wanted & {t.lower() for t in p.tags or []}]
    return rows


async def _validate_rules(session: AsyncSession, principal: Principal, rules: list[Any], project_id: uuid.UUID) -> None:
    """Every rule must reference a guardrail usable in the project."""
    for rule in rules:
        g = await enforcement.get_guardrail(session, principal, rule.guardrail_id)
        if g.project_id not in (None, project_id):
            raise HTTPException(422, "guardrail belongs to another project")


@router.post("/policies", response_model=PolicyOut, status_code=status.HTTP_201_CREATED, summary="Create a policy")
async def create_policy(body: PolicyIn, principal: CurrentPrincipal, session: Session) -> Policy:
    """Project policy binding guardrails to phases and severities."""
    project_id = principal.resolve_project(body.project_id)
    await _validate_rules(session, principal, body.rules, project_id)
    row = Policy(project_id=project_id, key=body.key, name=body.name, description=body.description,
                 rules=[r.model_dump(mode="json") for r in body.rules],
                 fail_on_severity_level=body.fail_on_severity_level, tags=body.tags, min_risk_tier=body.min_risk_tier)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"policy key {body.key!r} already exists") from exc
    await emit(session, project_id=project_id, event_type="policy.created", resource_type="policy",
               resource_id=row.id, actor=principal.subject)
    return row


async def _policy(session: AsyncSession, principal: Principal, policy_id: uuid.UUID) -> Policy:
    """A policy the caller may see."""
    row = await session.get(Policy, policy_id)
    if row is None or (row.project_id is not None and principal.visible_projects() is not None
                       and row.project_id not in principal.visible_projects()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "policy not found")
    return row


@router.get("/policies/{policy_id}", response_model=PolicyOut, summary="Get a policy")
async def get_policy(policy_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> Policy:
    """One policy."""
    return await _policy(session, principal, policy_id)


@router.patch("/policies/{policy_id}", response_model=PolicyOut, summary="Update a policy")
async def update_policy(policy_id: uuid.UUID, body: PolicyUpdate, principal: CurrentPrincipal, session: Session) -> Policy:
    """Edit a project policy."""
    row = await _policy(session, principal, policy_id)
    _check_editable(row, principal)
    if body.rules is not None:
        assert row.project_id is not None
        await _validate_rules(session, principal, body.rules, row.project_id)
        row.rules = [r.model_dump(mode="json") for r in body.rules]
    for field in ("name", "description", "fail_on_severity_level", "tags"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    await emit(session, project_id=row.project_id, event_type="policy.updated", resource_type="policy",
               resource_id=row.id, actor=principal.subject)
    return row


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a policy")
async def delete_policy(policy_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> Response:
    """Delete a project policy (detaches it from agents)."""
    row = await _policy(session, principal, policy_id)
    _check_editable(row, principal)
    await session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/policies/recommend", response_model=list[Recommendation], summary="Recommend policies")
async def recommend(body: RecommendIn, principal: CurrentPrincipal, session: Session) -> list[Recommendation]:
    """Ranked policies for an agent (tools, data, autonomy, risk tier) or for free-form tags."""
    ranked = await enforcement.recommend(session, principal, body.agent_id, body.tags, body.risk_tier)
    return [Recommendation(policy=PolicyOut.model_validate(r["policy"]), score=r["score"], reasons=r["reasons"],
                           attached=r["attached"]) for r in ranked]


@router.post("/enforce", response_model=EnforceOut, summary="Enforce an agent's policies on one message")
async def enforce(body: EnforceIn, principal: CurrentPrincipal, session: Session) -> EnforceOut:
    """Runtime guard and gateway entry point: evaluates every attached policy rule for the phase."""
    return await enforcement.enforce(session, principal, body)


# --------------------------------------------------------------------------------------------- metrics


@router.post("/metrics/{metric}", summary="Score text with one evaluator")
async def metric(metric: str, body: MetricIn, principal: CurrentPrincipal) -> dict[str, Any]:
    """Stand-alone scoring (pii also returns entities and a redacted copy)."""
    if metric not in EVALUATORS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown metric {metric!r}")
    params = dict(body.params)
    if body.policy:
        params["policy"] = body.policy
    if body.categories is not None:
        params["categories"] = body.categories
    if body.blocklist is not None:
        params["blocklist"] = body.blocklist
    outcome = await run_guardrail([{"type": metric, **params}], body.text, EvalContext(query=body.query))
    result = outcome.checks[0].to_dict()
    if metric == "pii":
        entities = find_pii(body.text, body.categories, body.blocklist)
        result["pii"] = [{"category": e.category, "start": e.start, "end": e.end, "masked": e.masked} for e in entities]
        result["redacted"] = redact(body.text, entities)
    return result
