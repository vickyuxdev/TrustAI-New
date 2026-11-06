"""
Projects and connectors no longer need a client: they attach to a hidden default client, and the per-client
endpoints keep working for existing integrations.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from shared.models.db import Client, ClientType, Connector, Project, UserClientRole, UserRole

API = "/api/v1"
PROJECT = {"name": "Expense Claim Checker", "slug": "expense-claim-checker", "monthly_budget_usd": 500.0}


async def count(sessionmaker_, model) -> int:
    async with sessionmaker_() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def make_client(sessionmaker_, slug: str) -> Client:
    async with sessionmaker_() as s:
        c = Client(name=slug.title(), slug=slug, client_type=ClientType.EXTERNAL)
        s.add(c)
        await s.commit()
        return c


# --------------------------------------------------------------------------------------------- POST /projects


@pytest.mark.asyncio
async def test_project_is_created_without_naming_a_client(api, sessionmaker_) -> None:
    res = await api.post(f"{API}/projects", json=PROJECT)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == PROJECT["name"] and body["monthly_budget_usd"] == 500.0
    async with sessionmaker_() as s:
        default = (await s.execute(select(Client).where(Client.slug == "default"))).scalar_one()
        assert str(default.id) == body["client_id"]


@pytest.mark.asyncio
async def test_projects_share_one_default_client(api, sessionmaker_) -> None:
    await api.post(f"{API}/projects", json=PROJECT)
    await api.post(f"{API}/projects", json={**PROJECT, "name": "Invoice Bot", "slug": "invoice-bot"})
    assert await count(sessionmaker_, Client) == 1
    assert await count(sessionmaker_, Project) == 2


@pytest.mark.asyncio
async def test_duplicate_slug_is_a_conflict(api) -> None:
    assert (await api.post(f"{API}/projects", json=PROJECT)).status_code == 201
    res = await api.post(f"{API}/projects", json=PROJECT)
    assert res.status_code == 409 and "already exists" in res.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_project_is_rejected(api) -> None:
    assert (await api.post(f"{API}/projects", json={"name": "x", "slug": "Bad Slug"})).status_code == 422


@pytest.mark.asyncio
async def test_only_admins_create_projects(api, caller, sessionmaker_) -> None:
    from shared.models.db import User

    default = await make_client(sessionmaker_, "default")
    oid = caller.as_user()  # an ordinary user with no role
    async with sessionmaker_() as s:
        user = User(azure_oid=oid, email="dev@test", display_name="Dev", is_super_admin=False)
        s.add(user)
        await s.commit()
    assert (await api.post(f"{API}/projects", json=PROJECT)).status_code == 403
    assert await count(sessionmaker_, Project) == 0

    # a client admin of the default client may create projects
    async with sessionmaker_() as s:
        s.add(UserClientRole(user_id=user.id, client_id=default.id, role=UserRole.CLIENT_ADMIN))
        await s.commit()
    assert (await api.post(f"{API}/projects", json=PROJECT)).status_code == 201


# --------------------------------------------------------------------------------------------- connectors


CONNECTOR = {"name": "App Insights", "provider": "azure_app_insights"}


@pytest.mark.asyncio
async def test_connector_without_client_or_project_uses_the_default_client(api, sessionmaker_) -> None:
    res = await api.post(f"{API}/connectors", json=CONNECTOR)
    assert res.status_code == 201, res.text
    async with sessionmaker_() as s:
        default = (await s.execute(select(Client).where(Client.slug == "default"))).scalar_one()
        assert res.json()["client_id"] == str(default.id)


@pytest.mark.asyncio
async def test_connector_follows_its_project_not_the_first_client(api, sessionmaker_) -> None:
    other = await make_client(sessionmaker_, "acme")
    async with sessionmaker_() as s:
        project = Project(client_id=other.id, name="Acme Bot", slug="acme-bot")
        s.add(project)
        await s.commit()
    res = await api.post(f"{API}/connectors", json={**CONNECTOR, "project_id": str(project.id)})
    assert res.status_code == 201, res.text
    assert res.json()["client_id"] == str(other.id) and res.json()["project_id"] == str(project.id)


@pytest.mark.asyncio
async def test_connector_for_an_unknown_project_or_mismatched_client_is_404(api, sessionmaker_) -> None:
    import uuid

    assert (await api.post(f"{API}/connectors", json={**CONNECTOR, "project_id": str(uuid.uuid4())})).status_code == 404
    other = await make_client(sessionmaker_, "acme")
    created = (await api.post(f"{API}/projects", json=PROJECT)).json()  # under the default client
    res = await api.post(f"{API}/connectors", json={**CONNECTOR, "project_id": created["id"], "client_id": str(other.id)})
    assert res.status_code == 404 and "under this client" in res.json()["detail"]
    assert await count(sessionmaker_, Connector) == 0


# --------------------------------------------------------------------------------------------- compatibility


@pytest.mark.asyncio
async def test_the_per_client_project_endpoint_still_works(api, sessionmaker_) -> None:
    client = await make_client(sessionmaker_, "acme")
    res = await api.post(f"{API}/clients/{client.id}/projects", json=PROJECT)
    assert res.status_code == 201 and res.json()["client_id"] == str(client.id)
