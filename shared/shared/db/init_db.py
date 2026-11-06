"""
shared/db/init_db.py
Database initialization script — creates all tables in both Metadata DB and Analytics DB.
"""
import asyncio
import logging

from shared.db.session import metadata_engine, analytics_engine
from shared.models.db import Base as MetadataBase
from shared.models.analytics_db import AnalyticsBase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("init_db")


async def init_databases():
    for attempt in range(1, 15):
        try:
            logger.info("Connecting and initializing Metadata database tables (attempt %d)...", attempt)
            async with metadata_engine.begin() as conn:
                await conn.run_sync(MetadataBase.metadata.create_all)
            logger.info("Metadata tables initialized successfully.")

            logger.info("Connecting and initializing Analytics database tables...")
            async with analytics_engine.begin() as conn:
                await conn.run_sync(AnalyticsBase.metadata.create_all)
            logger.info("Analytics tables initialized successfully.")
            return
        except Exception as exc:
            logger.warning("Database init attempt %d failed: %s. Retrying in 2s...", attempt, exc)
            await asyncio.sleep(2)
    raise RuntimeError("Failed to initialize databases after 15 attempts")


if __name__ == "__main__":
    asyncio.run(init_databases())
