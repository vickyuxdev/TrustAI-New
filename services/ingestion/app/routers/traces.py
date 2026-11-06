"""
services/ingestion/app/routers/traces.py
POST /v1/traces — main ingestion endpoint for span batches from the SDK.
"""
import json
import logging
import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.dependencies import (
    AuthenticatedProject,
    EventHubProducerClient,
    get_authenticated_project,
    get_event_hub_producer,
    publish_to_eventhub,
)
from shared.models.schemas import IngestBatch

logger = logging.getLogger("ingestion.traces")
router = APIRouter()


class IngestResponse(BaseModel):
    accepted: int
    batch_id: str


@router.post(
    "/traces",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a batch of telemetry spans",
    description=(
        "Accepts a batch of spans from the TrustAI SDK. "
        "Each span is validated, enriched with project/client context, "
        "and enqueued to the processing pipeline."
    ),
)
async def ingest_traces(
    batch: IngestBatch,
    auth: AuthenticatedProject = Depends(get_authenticated_project),
    producer: EventHubProducerClient = Depends(get_event_hub_producer),
) -> IngestResponse:
    batch_id = uuid.uuid4().hex

    # Resolve effective content capture mode per environment
    effective_capture = auth.project.get_content_capture_mode(batch.environment)

    # Strip content if capture is disabled at project level
    spans_data = []
    for span in batch.spans:
        span_dict = span.model_dump(exclude_none=True)
        if effective_capture == "disabled":
            span_dict.pop("input_content", None)
            span_dict.pop("output_content", None)
        span_dict["content_capture_mode"] = effective_capture.value
        spans_data.append(span_dict)

    # Build enriched payload for Event Hub
    payload = {
        "batch_id": batch_id,
        "client_id": str(auth.client_id),
        "project_id": str(auth.project_id),
        "environment": batch.environment,
        "agent_name": batch.agent_name,
        "sdk_version": batch.sdk_version,
        "spans": spans_data,
    }

    if producer is not None:
        await publish_to_eventhub(
            producer,
            payload,
            partition_key=str(auth.project_id),
        )
    else:
        # Direct DB write fallback for local development without Event Hub
        from shared.db.session import get_analytics_session, get_metadata_session
        from shared.models.analytics_db import SpanRecord, DailyRollup
        from datetime import datetime
        
        async with get_analytics_session() as a_db:
            async with get_metadata_session() as m_db:
                records = []
                total_cost = 0.0
                total_tokens = 0
                for s in spans_data:
                    started_at = datetime.fromisoformat(str(s.get("started_at")).replace("Z", "+00:00")) if s.get("started_at") else datetime.now(timezone.utc)
                    ended_at = datetime.fromisoformat(str(s.get("ended_at")).replace("Z", "+00:00")) if s.get("ended_at") else None
                    cost = s.get("cost_usd") or 0.0
                    total_cost += cost
                    total_tokens += (s.get("total_tokens") or 0)
                    rec = SpanRecord(
                        id=uuid.uuid4(),
                        trace_id=s.get("trace_id", ""),
                        span_id=s.get("span_id", ""),
                        parent_span_id=s.get("parent_span_id"),
                        client_id=auth.client_id,
                        project_id=auth.project_id,
                        environment=batch.environment,
                        span_name=s.get("span_name", "unknown"),
                        span_kind=s.get("span_kind", "internal"),
                        timestamp=started_at,
                        duration_ms=s.get("duration_ms"),
                        started_at=started_at,
                        ended_at=ended_at,
                        provider=s.get("provider"),
                        model_name=s.get("model_name"),
                        operation=s.get("operation"),
                        input_tokens=s.get("input_tokens"),
                        output_tokens=s.get("output_tokens"),
                        total_tokens=s.get("total_tokens"),
                        cached_tokens=s.get("cached_tokens"),
                        cost_usd=s.get("cost_usd"),
                        input_content=s.get("input_content"),
                        output_content=s.get("output_content"),
                        content_capture_mode=s.get("content_capture_mode"),
                        success=s.get("success", True),
                        finish_reason=s.get("finish_reason"),
                        tags=s.get("tags", {}),
                    )
                    records.append(rec)
                a_db.add_all(records)

                # Update daily rollup for live chart rendering
                today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                rollup = DailyRollup(
                    id=uuid.uuid4(),
                    day=today,
                    client_id=auth.client_id,
                    project_id=auth.project_id,
                    environment=batch.environment,
                    provider="azure_openai",
                    model_name=spans_data[0].get("model_name") if spans_data else None,
                    total_calls=len(records),
                    successful_calls=len(records),
                    failed_calls=0,
                    total_tokens=total_tokens,
                    total_cost_usd=total_cost,
                    avg_duration_ms=500.0,
                )
                a_db.add(rollup)

    logger.info(
        "Accepted batch",
        batch_id=batch_id,
        project_id=str(auth.project_id),
        span_count=len(spans_data),
    )

    return IngestResponse(accepted=len(spans_data), batch_id=batch_id)
