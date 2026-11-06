"""
services/admin/app/routers/pricing.py
Model pricing CRUD — configure cost per token per model/provider.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user, require_super_admin
from shared.db.session import metadata_session_dep
from shared.models.db import ModelPricing
from shared.models.schemas import ModelPricingCreate, ModelPricingResponse

router = APIRouter()

# Pre-configured defaults for common models
DEFAULT_PRICING = [
    {"provider": "azure_openai", "model_name": "gpt-4o",           "input_price_per_1m": 2.50,  "output_price_per_1m": 10.00, "cached_input_price_per_1m": 1.25},
    {"provider": "azure_openai", "model_name": "gpt-4o-mini",      "input_price_per_1m": 0.15,  "output_price_per_1m": 0.60,  "cached_input_price_per_1m": 0.075},
    {"provider": "azure_openai", "model_name": "gpt-4-turbo",      "input_price_per_1m": 10.00, "output_price_per_1m": 30.00},
    {"provider": "azure_openai", "model_name": "o1-preview",       "input_price_per_1m": 15.00, "output_price_per_1m": 60.00},
    {"provider": "azure_openai", "model_name": "o1-mini",          "input_price_per_1m": 3.00,  "output_price_per_1m": 12.00},
    {"provider": "openai",       "model_name": "gpt-4o",           "input_price_per_1m": 2.50,  "output_price_per_1m": 10.00, "cached_input_price_per_1m": 1.25},
    {"provider": "openai",       "model_name": "gpt-4o-mini",      "input_price_per_1m": 0.15,  "output_price_per_1m": 0.60},
]


@router.get("/pricing/models", response_model=list[ModelPricingResponse])
async def list_model_pricing(
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    result = await session.execute(
        select(ModelPricing).where(ModelPricing.is_active == True).order_by(ModelPricing.provider, ModelPricing.model_name)
    )
    return result.scalars().all()


@router.post("/pricing/models", response_model=ModelPricingResponse, status_code=status.HTTP_201_CREATED)
async def create_model_pricing(
    body: ModelPricingCreate,
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_super_admin()),
):
    from datetime import datetime, timezone
    pricing = ModelPricing(**body.model_dump(), effective_from=body.effective_from or datetime.now(timezone.utc))
    session.add(pricing)
    await session.flush()
    return ModelPricingResponse.model_validate(pricing)


@router.post("/pricing/models/seed", summary="Seed default model pricing")
async def seed_default_pricing(
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_super_admin()),
):
    """Seeds well-known model prices. Safe to call multiple times (idempotent by provider+model)."""
    from datetime import datetime, timezone
    added = 0
    for p in DEFAULT_PRICING:
        existing = await session.execute(
            select(ModelPricing).where(
                ModelPricing.provider == p["provider"],
                ModelPricing.model_name == p["model_name"],
                ModelPricing.is_active == True,
            )
        )
        if not existing.scalar_one_or_none():
            session.add(ModelPricing(
                **p,
                effective_from=datetime.now(timezone.utc),
            ))
            added += 1
    return {"seeded": added}


@router.delete("/pricing/models/{pricing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_pricing(
    pricing_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_super_admin()),
):
    pricing = await session.get(ModelPricing, pricing_id)
    if not pricing:
        raise HTTPException(status_code=404, detail="Pricing not found")
    pricing.is_active = False
