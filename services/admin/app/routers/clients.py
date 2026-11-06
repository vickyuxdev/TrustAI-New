"""
services/admin/app/routers/clients.py
Client CRUD — create, update, list clients with full onboarding support.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user, require_super_admin
from shared.db.session import metadata_session_dep
from shared.models.db import AuditLog, Client
from shared.models.schemas import ClientCreate, ClientResponse, ClientUpdate, PaginatedResponse

router = APIRouter()


@router.get(
    "/clients",
    response_model=PaginatedResponse,
    summary="List all clients",
)
async def list_clients(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    offset = (page - 1) * page_size
    result = await session.execute(
        select(Client)
        .where(Client.is_active == True)
        .order_by(Client.name)
        .offset(offset)
        .limit(page_size)
    )
    clients = result.scalars().all()

    count_result = await session.execute(
        select(func.count(Client.id)).where(Client.is_active == True)
    )
    total = count_result.scalar_one()

    items = [ClientResponse.model_validate(c) for c in clients]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get(
    "/clients/{client_id}",
    response_model=ClientResponse,
    summary="Get client details",
)
async def get_client(
    client_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientResponse.model_validate(client)



@router.post(
    "/clients",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard a new client",
)
async def create_client(
    body: ClientCreate,
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_super_admin()),
):
    # Check slug uniqueness
    existing = await session.execute(select(Client).where(Client.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' is already taken")

    client = Client(**body.model_dump())
    session.add(client)
    session.add(AuditLog(
        user_id=current_user.id,
        action="create_client",
        resource_type="client",
        resource_id=str(client.id),
        new_value=body.model_dump(),
    ))
    await session.flush()
    return ClientResponse.model_validate(client)


@router.patch("/clients/{client_id}", response_model=ClientResponse)
async def update_client(
    body: ClientUpdate,
    client_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_super_admin()),
):
    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(client, field, value)

    session.add(AuditLog(
        user_id=current_user.id,
        action="update_client",
        resource_type="client",
        resource_id=str(client_id),
        new_value=body.model_dump(exclude_none=True),
    ))
    return ClientResponse.model_validate(client)


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_client(
    client_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_super_admin()),
):
    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.is_active = False
    session.add(AuditLog(
        user_id=current_user.id,
        action="deactivate_client",
        resource_type="client",
        resource_id=str(client_id),
    ))
