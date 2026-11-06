"""
services/api/app/routers/alerts.py
Alert rules and fired alert management.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user
from shared.db.session import metadata_session_dep
from shared.models.db import AlertRule, FiredAlert, AlertStatus
from shared.models.schemas import AlertRuleCreate, AlertRuleResponse, FiredAlertResponse, PaginatedResponse

router = APIRouter()


@router.get("/alert-rules", response_model=PaginatedResponse, summary="List alert rules")
async def list_alert_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    from sqlalchemy import func
    count_result = await session.execute(select(func.count(AlertRule.id)))
    total = count_result.scalar_one()

    q = select(AlertRule).order_by(AlertRule.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    rules = result.scalars().all()

    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[AlertRuleResponse.model_validate(r) for r in rules]
    )


@router.post("/alert-rules", response_model=AlertRuleResponse, summary="Create alert rule", status_code=201)
async def create_alert_rule(
    payload: AlertRuleCreate,
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    rule = AlertRule(
        name=payload.name,
        metric=payload.metric,
        operator=payload.operator,
        threshold=payload.threshold,
        window_minutes=payload.window_minutes,
        severity=payload.severity,
        notification_channels=payload.notification_channels,
        project_id=payload.project_id,
        is_active=True,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return AlertRuleResponse.model_validate(rule)


@router.delete("/alert-rules/{rule_id}", summary="Delete alert rule", status_code=204)
async def delete_alert_rule(
    rule_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await session.delete(rule)
    await session.commit()


@router.get("/alerts", response_model=PaginatedResponse, summary="List alerts")
async def list_alerts(
    status: str | None = Query(default=None, description="Filter by status: active, acknowledged, resolved, or omit for all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    q = select(FiredAlert).join(AlertRule)
    if status and status != "all":
        try:
            q = q.where(FiredAlert.status == AlertStatus(status))
        except ValueError:
            pass  # ignore invalid status values

    from sqlalchemy import func
    count_result = await session.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar_one()

    q = q.order_by(FiredAlert.triggered_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    alerts = result.scalars().all()

    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[FiredAlertResponse.model_validate(a) for a in alerts]
    )


@router.patch("/alerts/{alert_id}/acknowledge", summary="Acknowledge an alert")
async def acknowledge_alert(
    alert_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    from datetime import datetime, timezone
    alert = await session.get(FiredAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = current_user.id
    await session.commit()
    return {"status": "acknowledged"}


@router.patch("/alerts/{alert_id}/resolve", summary="Resolve an alert")
async def resolve_alert(
    alert_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    from datetime import datetime, timezone
    alert = await session.get(FiredAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "resolved"}
