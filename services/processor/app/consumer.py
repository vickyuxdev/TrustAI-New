"""
services/processor/app/consumer.py
Event Hub consumer — reads span batches, enriches them, and persists to
the analytics database.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from azure.eventhub.aio import EventHubConsumerClient

from shared.config import EventHubSettings
from shared.db.session import get_analytics_session, get_metadata_session
from shared.models.analytics_db import SpanRecord
from shared.models.db import Agent, Project

from app.cost_engine import compute_span_cost
from app.enricher import resolve_agent_id

logger = logging.getLogger("processor.consumer")
_settings = EventHubSettings()


async def process_event_batch(events) -> None:
    """Process a batch of Event Hub events."""
    async with get_analytics_session() as analytics_db:
        async with get_metadata_session() as meta_db:
            for event in events:
                try:
                    payload = json.loads(event.body_as_str())
                    await _process_payload(payload, analytics_db, meta_db)
                except Exception as exc:
                    logger.error("Failed to process event: %s", exc)


async def _process_payload(
    payload: dict,
    analytics_db,
    meta_db,
) -> None:
    client_id = uuid.UUID(payload["client_id"])
    project_id = uuid.UUID(payload["project_id"])
    environment = payload.get("environment", "production")
    agent_name = payload.get("agent_name")
    spans_data = payload.get("spans", [])

    # Resolve agent_id if agent_name is provided
    agent_id = None
    if agent_name:
        agent_id = await resolve_agent_id(meta_db, project_id, agent_name)

    records = []
    for span_dict in spans_data:
        # Parse timestamps
        started_at = _parse_dt(span_dict.get("started_at"))
        ended_at = _parse_dt(span_dict.get("ended_at"))
        duration_ms = span_dict.get("duration_ms")
        if not duration_ms and started_at and ended_at:
            duration_ms = (ended_at - started_at).total_seconds() * 1000

        # Cost computation using model pricing from metadata DB
        cost_usd = span_dict.get("cost_usd")
        if cost_usd is None:
            cost_usd = await compute_span_cost(
                meta_db,
                provider=span_dict.get("provider"),
                model_name=span_dict.get("model_name"),
                input_tokens=span_dict.get("input_tokens"),
                output_tokens=span_dict.get("output_tokens"),
                cached_tokens=span_dict.get("cached_tokens"),
            )

        record = SpanRecord(
            id=uuid.uuid4(),
            trace_id=span_dict.get("trace_id", ""),
            span_id=span_dict.get("span_id", ""),
            parent_span_id=span_dict.get("parent_span_id"),
            client_id=client_id,
            project_id=project_id,
            agent_id=agent_id,
            environment=environment,
            span_name=span_dict.get("span_name", "unknown"),
            span_kind=span_dict.get("span_kind", "internal"),
            timestamp=started_at or datetime.now(timezone.utc),
            duration_ms=duration_ms,
            started_at=started_at,
            ended_at=ended_at,
            provider=span_dict.get("provider"),
            model_name=span_dict.get("model_name"),
            model_version=span_dict.get("model_version"),
            operation=span_dict.get("operation"),
            input_tokens=span_dict.get("input_tokens"),
            output_tokens=span_dict.get("output_tokens"),
            total_tokens=span_dict.get("total_tokens"),
            cached_tokens=span_dict.get("cached_tokens"),
            reasoning_tokens=span_dict.get("reasoning_tokens"),
            cost_usd=cost_usd,
            input_content=span_dict.get("input_content"),
            output_content=span_dict.get("output_content"),
            content_capture_mode=span_dict.get("content_capture_mode"),
            success=span_dict.get("success", True),
            error_type=span_dict.get("error_type"),
            error_message=span_dict.get("error_message"),
            finish_reason=span_dict.get("finish_reason"),
            source_provider="trustai_sdk",
            raw_attributes=span_dict.get("attributes", {}),
            tags=span_dict.get("tags", {}),
        )
        records.append(record)

    analytics_db.add_all(records)
    logger.info("Persisted %d spans for project %s", len(records), project_id)


def _parse_dt(v) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


async def start_consumer() -> None:
    """Start the Event Hub consumer loop."""
    conn_str = _settings.connection_string.get_secret_value()
    if not conn_str:
        logger.warning("Event Hub not configured — processor running in dry-run mode")
        await asyncio.sleep(float("inf"))
        return

    checkpoint_store = None
    checkpoint_url = _settings.checkpoint_store_url
    if checkpoint_url:
        try:
            from azure.eventhub.extensions.checkpointstoreblob.aio import BlobCheckpointStore
            checkpoint_store = BlobCheckpointStore.from_connection_string(
                checkpoint_url, "trustai-checkpoints"
            )
        except ImportError:
            logger.warning(
                "azure-eventhub-checkpointstoreblob-aio not installed; "
                "running without checkpoint store"
            )

    client = EventHubConsumerClient.from_connection_string(
        conn_str=conn_str,
        consumer_group=_settings.consumer_group,
        eventhub_name=_settings.eventhub_name,
        checkpoint_store=checkpoint_store,
    )

    logger.info("Starting Event Hub consumer on %s", _settings.eventhub_name)
    async with client:
        await client.receive_batch(
            on_event_batch=process_event_batch,
            max_batch_size=100,
            max_wait_time=5,
        )
