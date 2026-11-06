"""
bootstrap_demo.py
Quick setup script to register a test Client, Project, and API Key in TrustAI.
"""
import asyncio
import os
import sys
import uuid
import hashlib

# Ensure shared package and trustai-sdk are in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "trustai-sdk"))

from shared.db.session import get_metadata_session
from shared.models.db import Client, Project, ApiKey, ClientType, ContentCaptureMode, ApiKeyStatus, ModelPricing

async def seed_trustai():
    # 1. Initialize tables first
    from shared.models.db import Base as MetadataBase
    from shared.db.session import metadata_engine
    
    print("⏳ Connecting to TrustAI Database...")
    try:
        async with metadata_engine.begin() as conn:
            await conn.run_sync(MetadataBase.metadata.create_all)
    except Exception as e:
        print(f"\n❌ Could not connect to PostgreSQL on localhost:5432.")
        print(f"Error: {e}")
        print("\n💡 TIP: If Docker is running, you can run this script directly inside the container:")
        print("   docker compose exec ingestion python bootstrap_demo.py\n")
        return

    async with get_metadata_session() as session:
        # 1. Create Model Pricing
        pricing = ModelPricing(
            provider="azure_openai",
            model_name="gpt-5.4-mini",
            input_price_per_1m=0.75,
            output_price_per_1m=4.50,
        )
        session.add(pricing)

        # 2. Create Client
        client = Client(
            name="Cooling Tower POC",
            slug="cooling-tower-poc",
            client_type=ClientType.INTERNAL,
            description="Internal Cooling Tower AI Monitoring POC",
            monthly_budget_usd=2000.0,
        )
        session.add(client)
        await session.flush()

        # 3. Create Project
        project = Project(
            client_id=client.id,
            name="Cooling Tower Diagnostics",
            slug="cooling-tower-diagnostics",
            description="LLM Agent for Cooling Tower anomaly diagnostics",
            content_capture_mode=ContentCaptureMode.FULL,
        )
        session.add(project)
        await session.flush()

        # 4. Create API Key
        raw_key = "tai_live_demo_cooling_tower_12345"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = ApiKey(
            project_id=project.id,
            name="Default Ingestion Key",
            key_prefix=raw_key[:16],
            key_hash=key_hash,
            status=ApiKeyStatus.ACTIVE,
            scopes=["ingest"],
        )
        session.add(api_key)
        await session.flush()

        print("\n" + "="*60)
        print("✅ TrustAI Project Successfully Seeded!")
        print("="*60)
        print(f"Client ID:    {client.id}")
        print(f"Project ID:   {project.id}")
        print(f"Project Slug: {project.slug}")
        print(f"API Key:      {raw_key}")
        print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(seed_trustai())
