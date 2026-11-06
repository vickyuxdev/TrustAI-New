"""
services/collector/app/main.py
APScheduler-based collector that runs every N minutes per connector.
"""
import asyncio
import json
import signal
from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from shared.crypto import decrypt_secret
from shared.db.session import get_metadata_session
from shared.models.db import Connector, ConnectorProvider

log = structlog.get_logger()

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)


def _get_adapter(provider: ConnectorProvider, config: dict, creds: dict):
    """Return the correct adapter instance for a provider."""
    from app.adapters.azure_openai import AzureOpenAIAdapter
    from app.adapters.azure_app_insights import AzureAppInsightsAdapter
    from app.adapters.azure_foundry import AzureFoundryAdapter
    from app.adapters.aws_bedrock import AWSBedrockAdapter

    mapping = {
        ConnectorProvider.AZURE_OPENAI: AzureOpenAIAdapter,
        ConnectorProvider.AZURE_APP_INSIGHTS: AzureAppInsightsAdapter,
        ConnectorProvider.AZURE_FOUNDRY: AzureFoundryAdapter,
        ConnectorProvider.AWS_BEDROCK: AWSBedrockAdapter,
    }
    cls = mapping.get(provider)
    if not cls:
        return None
    return cls(config, creds)


async def sync_connector(connector_id: str) -> int:
    """
    Sync a single connector — fetch metrics and write to DB.
    Returns number of records written.
    """
    from app.writer import write_metrics, write_spans
    from shared.db.session import get_metadata_session

    async with get_metadata_session() as session:
        import uuid
        conn = await session.get(Connector, uuid.UUID(connector_id))
        if not conn or not conn.is_active:
            return 0

        creds: dict = {}
        if conn.credentials_encrypted:
            try:
                creds = json.loads(decrypt_secret(conn.credentials_encrypted))
            except Exception as exc:
                log.error("collector.decrypt_failed", connector_id=connector_id, error=str(exc))
                conn.last_sync_status = "error"
                conn.last_sync_error = f"Decrypt failed: {exc}"
                await session.commit()
                return 0

        adapter = _get_adapter(conn.provider, conn.config or {}, creds)
        if not adapter:
            log.warning("collector.no_adapter", provider=str(conn.provider))
            return 0

        now = datetime.now(timezone.utc)
        since = conn.last_sync_at or (now - timedelta(hours=24))

        log.info(
            "collector.sync_start",
            connector_id=connector_id,
            provider=str(conn.provider),
            name=conn.name,
            since=since.isoformat(),
        )

        try:
            conn.last_sync_status = "running"
            await session.commit()

            # 1. Ingest granular spans (if supported by adapter)
            spans_written = 0
            if hasattr(adapter, "fetch_spans"):
                try:
                    spans = await adapter.fetch_spans(
                        connector_id=connector_id,
                        client_id=str(conn.client_id),
                        project_id=str(conn.project_id) if conn.project_id else None,
                        since=since,
                        until=now,
                    )
                    spans_written = await write_spans(
                        spans=spans,
                        client_id=conn.client_id,
                        project_id=conn.project_id,
                    )
                except Exception as s_exc:
                    log.error("collector.spans_error", connector_id=connector_id, error=str(s_exc))

            # 2. Ingest aggregate metrics & rollups
            metrics = await adapter.fetch(
                connector_id=connector_id,
                client_id=str(conn.client_id),
                project_id=str(conn.project_id) if conn.project_id else None,
                since=since,
                until=now,
            )

            records = await write_metrics(metrics)
            total_records = spans_written + records

            conn.last_sync_at = now
            conn.last_sync_status = "ok"
            conn.last_sync_error = None
            conn.last_sync_records = total_records
            await session.commit()

            log.info(
                "collector.sync_done",
                connector_id=connector_id,
                spans_written=spans_written,
                metrics_written=records,
            )
            return total_records

        except Exception as exc:
            log.error("collector.sync_error", connector_id=connector_id, error=str(exc))
            conn.last_sync_status = "error"
            conn.last_sync_error = str(exc)[:500]
            conn.last_sync_at = now
            await session.commit()
            return 0


async def sync_all() -> None:
    """Called by scheduler — fetches all active connectors and syncs them."""
    log.info("collector.tick_start")
    try:
        async with get_metadata_session() as session:
            result = await session.execute(
                select(Connector).where(Connector.is_active == True)
            )
            connectors = result.scalars().all()
            connector_ids = [str(c.id) for c in connectors]

        log.info("collector.found_connectors", count=len(connector_ids))

        # Run all syncs concurrently (with some backpressure)
        tasks = [sync_connector(cid) for cid in connector_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total = sum(r for r in results if isinstance(r, int))
        errors = sum(1 for r in results if isinstance(r, Exception))
        log.info("collector.tick_done", total_records=total, errors=errors)

    except Exception as exc:
        log.error("collector.tick_failed", error=str(exc))


async def main():
    log.info("collector.starting")
    scheduler = AsyncIOScheduler()

    # Default: run every 10 minutes
    scheduler.add_job(sync_all, IntervalTrigger(minutes=10), id="sync_all", max_instances=1)

    # Run once immediately on startup
    scheduler.add_job(sync_all, id="sync_all_startup", max_instances=1)

    scheduler.start()
    log.info("collector.scheduler_started", interval_minutes=10)

    # Keep running
    stop_event = asyncio.Event()

    def _stop():
        stop_event.set()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, _stop)
    loop.add_signal_handler(signal.SIGINT, _stop)

    await stop_event.wait()
    scheduler.shutdown(wait=False)
    log.info("collector.stopped")


if __name__ == "__main__":
    asyncio.run(main())
