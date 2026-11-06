"""
services/processor/app/enricher.py
Resolves span metadata to database entity IDs (agents, etc.).
Auto-creates Agent records on first sight.
"""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared.models.db import Agent


async def resolve_agent_id(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_name: str,
) -> uuid.UUID:
    """
    Resolve an agent name to its UUID, creating the Agent record if it
    doesn't exist yet (auto-discovery of new agents from SDK events).
    """
    slug = agent_name.lower().replace(" ", "-").replace("_", "-")[:100]

    result = await session.execute(
        select(Agent).where(Agent.project_id == project_id, Agent.slug == slug)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        agent = Agent(
            project_id=project_id,
            name=agent_name,
            slug=slug,
        )
        session.add(agent)
        await session.flush()

    return agent.id
