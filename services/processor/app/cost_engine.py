"""
services/processor/app/cost_engine.py
Server-side cost computation using ModelPricing records from the metadata DB.
Falls back gracefully if no pricing is configured.
"""
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.db import ModelPricing

logger = logging.getLogger("processor.cost_engine")

# In-memory cache to avoid DB hits per span
_pricing_cache: dict[tuple, ModelPricing | None] = {}


async def _get_pricing(
    session: AsyncSession,
    provider: str | None,
    model_name: str | None,
) -> ModelPricing | None:
    if not provider or not model_name:
        return None

    cache_key = (provider, model_name)
    if cache_key in _pricing_cache:
        return _pricing_cache[cache_key]

    result = await session.execute(
        select(ModelPricing)
        .where(
            ModelPricing.provider == provider,
            ModelPricing.model_name == model_name,
            ModelPricing.is_active == True,
        )
        .order_by(ModelPricing.effective_from.desc())
        .limit(1)
    )
    pricing = result.scalar_one_or_none()
    _pricing_cache[cache_key] = pricing
    return pricing


async def compute_span_cost(
    session: AsyncSession,
    provider: str | None,
    model_name: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None = None,
) -> float | None:
    pricing = await _get_pricing(session, provider, model_name)
    if not pricing:
        return None
    if input_tokens is None or output_tokens is None:
        return None

    cached = cached_tokens or 0
    cached_price = pricing.cached_input_price_per_1m or pricing.input_price_per_1m
    uncached = max(0, input_tokens - cached)

    cost = (
        (uncached / 1_000_000) * pricing.input_price_per_1m
        + (cached / 1_000_000) * cached_price
        + (output_tokens / 1_000_000) * pricing.output_price_per_1m
    )
    return round(cost, 6)


def invalidate_pricing_cache() -> None:
    """Call after updating ModelPricing records."""
    global _pricing_cache
    _pricing_cache = {}
