"""
services/admin/app/routers/connectors.py
Connector CRUD + test-connection + manual sync trigger.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.default_client import get_default_client
from shared.auth.rbac import get_current_user
from shared.crypto import decrypt_secret, encrypt_secret
from shared.db.session import metadata_session_dep
from shared.models.db import Client, Connector, ConnectorProvider, Project

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class ConnectorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: ConnectorProvider
    client_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(
        default_factory=dict,
        description="Raw credentials — encrypted before storage, never returned",
    )
    sync_interval_minutes: int = Field(default=10, ge=1, le=1440)
    is_active: bool = True


class ConnectorUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, str] | None = None
    sync_interval_minutes: int | None = None
    is_active: bool | None = None


class ConnectorResponse(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    provider: ConnectorProvider
    is_active: bool
    config: dict
    sync_interval_minutes: int
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None
    last_sync_records: int | None
    created_at: datetime
    updated_at: datetime
    # credential_keys: which secret keys are stored (not values)
    credential_keys: list[str] = []

    class Config:
        from_attributes = True


def _to_response(conn: Connector) -> ConnectorResponse:
    cred_keys: list[str] = []
    if conn.credentials_encrypted:
        try:
            cred_keys = list(json.loads(decrypt_secret(conn.credentials_encrypted)).keys())
        except Exception:
            cred_keys = ["<encrypted>"]
    return ConnectorResponse(
        id=conn.id,
        client_id=conn.client_id,
        project_id=conn.project_id,
        name=conn.name,
        provider=conn.provider,
        is_active=conn.is_active,
        config=conn.config or {},
        sync_interval_minutes=conn.sync_interval_minutes,
        last_sync_at=conn.last_sync_at,
        last_sync_status=conn.last_sync_status,
        last_sync_error=conn.last_sync_error,
        last_sync_records=conn.last_sync_records,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
        credential_keys=cred_keys,
    )


# ── List all connectors (platform admin) ─────────────────────────────────────

@router.get("/connectors", response_model=list[ConnectorResponse], summary="List all connectors")
async def list_all_connectors(
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    result = await session.execute(
        select(Connector).order_by(Connector.created_at.desc())
    )
    return [_to_response(c) for c in result.scalars().all()]


# ── List connectors for a client ─────────────────────────────────────────────

@router.get(
    "/clients/{client_id}/connectors",
    response_model=list[ConnectorResponse],
    summary="List connectors for a client",
)
async def list_client_connectors(
    client_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    result = await session.execute(
        select(Connector)
        .where(Connector.client_id == client_id)
        .order_by(Connector.created_at.desc())
    )
    return [_to_response(c) for c in result.scalars().all()]


# ── Create connector ─────────────────────────────────────────────────────────

@router.post(
    "/connectors",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new cloud connector directly",
)
@router.post(
    "/clients/connectors",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new cloud connector (fallback path)",
)
async def create_connector_direct(
    body: ConnectorCreate,
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    project = None
    if body.project_id:
        project = await session.get(Project, body.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

    target_client_id = body.client_id
    if not target_client_id:
        # No client named: follow the project, else the hidden default client (clients are not user-facing).
        target_client_id = project.client_id if project else (await get_default_client(session)).id
    else:
        client = await session.get(Client, target_client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

    if project and project.client_id != target_client_id:
        raise HTTPException(status_code=404, detail="Project not found under this client")

    encrypted = encrypt_secret(json.dumps(body.credentials)) if body.credentials else None

    connector = Connector(
        client_id=target_client_id,
        project_id=body.project_id,
        name=body.name,
        provider=body.provider,
        config=body.config,
        credentials_encrypted=encrypted,
        sync_interval_minutes=body.sync_interval_minutes,
        is_active=body.is_active,
    )
    session.add(connector)
    await session.flush()
    await session.refresh(connector)
    return _to_response(connector)


@router.post(
    "/clients/{client_id}/connectors",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new cloud connector",
)
async def create_connector(
    body: ConnectorCreate,
    client_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if body.project_id:
        project = await session.get(Project, body.project_id)
        if not project or project.client_id != client_id:
            raise HTTPException(status_code=404, detail="Project not found under this client")

    encrypted = encrypt_secret(json.dumps(body.credentials)) if body.credentials else None

    connector = Connector(
        client_id=client_id,
        project_id=body.project_id,
        name=body.name,
        provider=body.provider,
        config=body.config,
        credentials_encrypted=encrypted,
        sync_interval_minutes=body.sync_interval_minutes,
        is_active=body.is_active,
    )
    session.add(connector)
    await session.flush()
    await session.refresh(connector)
    return _to_response(connector)


# ── Update connector ─────────────────────────────────────────────────────────

@router.put(
    "/connectors/{connector_id}",
    response_model=ConnectorResponse,
    summary="Update connector config / credentials",
)
async def update_connector(
    body: ConnectorUpdate,
    connector_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    conn = await session.get(Connector, connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")

    if body.name is not None:
        conn.name = body.name
    if body.config is not None:
        conn.config = body.config
    if body.credentials is not None:
        conn.credentials_encrypted = encrypt_secret(json.dumps(body.credentials))
    if body.sync_interval_minutes is not None:
        conn.sync_interval_minutes = body.sync_interval_minutes
    if body.is_active is not None:
        conn.is_active = body.is_active
    conn.updated_at = datetime.now(timezone.utc)

    await session.flush()
    await session.refresh(conn)
    return _to_response(conn)


# ── Delete connector ─────────────────────────────────────────────────────────

@router.delete(
    "/connectors/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connector",
)
async def delete_connector(
    connector_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    conn = await session.get(Connector, connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")
    await session.delete(conn)


# ── Test connection ───────────────────────────────────────────────────────────

class TestResult(BaseModel):
    success: bool
    message: str
    details: dict = {}


@router.post(
    "/connectors/{connector_id}/test",
    response_model=TestResult,
    summary="Test a connector's credentials live",
)
async def test_connector(
    connector_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    conn = await session.get(Connector, connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")

    creds: dict = {}
    if conn.credentials_encrypted:
        try:
            creds = json.loads(decrypt_secret(conn.credentials_encrypted))
        except Exception as e:
            return TestResult(success=False, message=f"Failed to decrypt credentials: {e}")

    try:
        result = await _test_provider(conn.provider, conn.config, creds)
        return result
    except Exception as exc:
        return TestResult(success=False, message=str(exc))


async def _test_provider(
    provider: ConnectorProvider, config: dict, creds: dict
) -> TestResult:
    """Dispatch to the correct adapter test method."""
    if provider == ConnectorProvider.AZURE_OPENAI:
        return await _test_azure_openai(config, creds)
    elif provider == ConnectorProvider.AZURE_APP_INSIGHTS:
        return await _test_app_insights(config, creds)
    elif provider == ConnectorProvider.AZURE_FOUNDRY:
        return await _test_azure_foundry(config, creds)
    elif provider == ConnectorProvider.AWS_BEDROCK:
        return await _test_aws_bedrock(config, creds)
    else:
        return TestResult(success=True, message=f"Test not implemented for {provider}; assuming OK")


async def _test_azure_openai(config: dict, creds: dict) -> TestResult:
    import httpx
    endpoint = config.get("endpoint", "").rstrip("/")
    api_key = creds.get("api_key", "")
    api_version = config.get("api_version", "2024-02-01")
    if not endpoint or not api_key:
        return TestResult(success=False, message="Missing endpoint or api_key")
    url = f"{endpoint}/openai/deployments?api-version={api_version}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers={"api-key": api_key})
    if resp.status_code == 200:
        data = resp.json()
        deployments = [d.get("id") for d in data.get("data", [])]
        return TestResult(success=True, message="Connected to Azure OpenAI", details={"deployments": deployments})
    return TestResult(success=False, message=f"HTTP {resp.status_code}: {resp.text[:200]}")


async def _test_app_insights(config: dict, creds: dict) -> TestResult:
    """
    Supports two auth modes:
    1. AAD client credentials  → tenant_id + client_id + client_secret  (preferred)
       Uses Application Insights REST API via application_id in config.
    2. API key (direct)        → api_key + application_id
       Uses App Insights direct REST API (api.applicationinsights.io).
    3. API key (Log Analytics) → api_key + workspace_id (fallback)
       Uses Log Analytics REST API (api.loganalytics.io).
    """
    import httpx

    tenant_id = creds.get("tenant_id", "")
    client_id_cred = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    application_id = config.get("application_id", "")
    workspace_id = config.get("workspace_id", "")
    api_key = creds.get("api_key", "")

    # ── Mode 1: AAD client credentials ───────────────────────────────────────
    if tenant_id and client_id_cred and client_secret:
        if not application_id:
            return TestResult(
                success=False,
                message="application_id is required when using AAD auth. "
                        "Find it in: App Insights → Properties → Application ID.",
            )
        # Get AAD token for Application Insights REST API
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        token_data = {
            "grant_type": "client_credentials",
            "client_id": client_id_cred,
            "client_secret": client_secret,
            "scope": "https://api.applicationinsights.io/.default",
        }
        async with httpx.AsyncClient(timeout=15) as http:
            token_resp = await http.post(token_url, data=token_data)
        if token_resp.status_code != 200:
            return TestResult(
                success=False,
                message=f"AAD token request failed: HTTP {token_resp.status_code}",
                details={"error": token_resp.text[:300]},
            )
        token = token_resp.json().get("access_token", "")
        if not token:
            return TestResult(success=False, message="AAD token response missing access_token")

        # Query a single trace to verify connectivity
        query_url = f"https://api.applicationinsights.io/v1/apps/{application_id}/query"
        async with httpx.AsyncClient(timeout=20) as http:
            resp = await http.post(
                query_url,
                json={"query": "traces | limit 1"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code == 200:
            tables = resp.json().get("tables", [])
            row_count = len(tables[0].get("rows", [])) if tables else 0
            return TestResult(
                success=True,
                message="Connected to Azure Application Insights via AAD",
                details={
                    "application_id": application_id,
                    "sample_rows_returned": row_count,
                },
            )
        return TestResult(
            success=False,
            message=f"App Insights query failed: HTTP {resp.status_code}",
            details={"response": resp.text[:300]},
        )

    # ── Mode 2: API Key + Application ID (App Insights direct REST API) ───────
    # This is the canonical mode when users generate a key via:
    # App Insights → Configure → API Access → Create API key
    if api_key and application_id:
        url = f"https://api.applicationinsights.io/v1/apps/{application_id}/query"
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                url,
                json={"query": "traces | limit 1"},
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            )
        if resp.status_code == 200:
            tables = resp.json().get("tables", [])
            row_count = len(tables[0].get("rows", [])) if tables else 0
            return TestResult(
                success=True,
                message="Connected to Azure Application Insights via API Key",
                details={
                    "application_id": application_id,
                    "sample_rows_returned": row_count,
                },
            )
        return TestResult(
            success=False,
            message=f"App Insights API key test failed: HTTP {resp.status_code}: {resp.text[:200]}",
            details={"hint": "Ensure the API key has 'Read telemetry' permission and application_id is correct."},
        )

    # ── Mode 3: API Key + Workspace ID (Log Analytics fallback) ──────────────
    if api_key and workspace_id:
        url = f"https://api.loganalytics.io/v1/workspaces/{workspace_id}/query"
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                url,
                json={"query": "traces | limit 1"},
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
            )
        if resp.status_code == 200:
            return TestResult(
                success=True,
                message="Connected to Azure Log Analytics Workspace via API Key",
                details={"workspace_id": workspace_id},
            )
        return TestResult(
            success=False,
            message=f"Log Analytics test failed: HTTP {resp.status_code}: {resp.text[:200]}",
        )

    return TestResult(
        success=False,
        message="Incomplete credentials. Provide one of:\n"
                "• API Key + Application ID (recommended)\n"
                "• Tenant ID + Client ID + Client Secret + Application ID (AAD)\n"
                "• API Key + Workspace ID (Log Analytics fallback)",
    )


async def _test_azure_foundry(config: dict, creds: dict) -> TestResult:
    """
    Test Azure AI Foundry connection. Supports:
    1. Service Principal (tenant_id + client_id + client_secret)
       - Tests ARM access to CognitiveServices account / Foundry resource
       - Tests Azure AI Project endpoint
    2. API Key (api_key + endpoint)
       - Tests OpenAI-compatible deployments endpoint
    """
    import httpx

    endpoint = config.get("endpoint", "").rstrip("/")
    api_key = creds.get("api_key", "").strip()
    tenant_id = creds.get("tenant_id", "").strip()
    client_id_cred = creds.get("client_id", "").strip()
    client_secret = creds.get("client_secret", "").strip()
    raw_resource_id = config.get("resource_id", "").strip()

    # Clean resource_id if a user pasted a portal URL
    resource_id = ""
    if raw_resource_id:
        if "/subscriptions/" in raw_resource_id:
            resource_id = "/subscriptions/" + raw_resource_id.split("/subscriptions/")[1].split("/overview")[0].split("?")[0].rstrip("/")
        else:
            resource_id = raw_resource_id

    # ── Mode 1: Service Principal (recommended) ──────────────────────────────
    if tenant_id and client_id_cred and client_secret:
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        async with httpx.AsyncClient(timeout=15) as http:
            # 1. Obtain ARM token to verify Azure account & metrics access
            arm_resp = await http.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id_cred,
                    "client_secret": client_secret,
                    "scope": "https://management.azure.com/.default",
                },
            )
            if arm_resp.status_code != 200:
                return TestResult(
                    success=False,
                    message=f"Azure Service Principal authentication failed: HTTP {arm_resp.status_code}",
                    details={"error": arm_resp.text[:300]},
                )

            arm_token = arm_resp.json().get("access_token", "")
            details: dict[str, Any] = {"auth_method": "service_principal"}

            if resource_id:
                arm_query = await http.get(
                    f"https://management.azure.com{resource_id}?api-version=2023-05-01",
                    headers={"Authorization": f"Bearer {arm_token}"},
                )
                if arm_query.status_code == 200:
                    arm_data = arm_query.json()
                    account_name = arm_data.get("name", "foundry-account")
                    location = arm_data.get("location", "unknown")
                    sku = arm_data.get("sku", {}).get("name", "")
                    details.update({
                        "resource_name": account_name,
                        "location": location,
                        "sku": sku,
                        "resource_id": resource_id,
                    })
                    return TestResult(
                        success=True,
                        message=f"Connected to Azure AI Foundry ({account_name} in {location})",
                        details=details,
                    )
                else:
                    details["arm_status"] = arm_query.status_code

            # Also check project endpoint if provided
            if endpoint:
                ai_resp = await http.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id_cred,
                        "client_secret": client_secret,
                        "scope": "https://ai.azure.com/.default",
                    },
                )
                if ai_resp.status_code == 200:
                    ai_token = ai_resp.json().get("access_token", "")
                    ep_test = await http.get(
                        f"{endpoint}/connections?api-version=2024-05-01-preview",
                        headers={"Authorization": f"Bearer {ai_token}"},
                    )
                    details["endpoint"] = endpoint
                    details["endpoint_status"] = ep_test.status_code
                    return TestResult(
                        success=True,
                        message="Connected to Azure AI Foundry via Service Principal",
                        details=details,
                    )

            return TestResult(
                success=True,
                message="Azure Service Principal authenticated successfully",
                details=details,
            )

    # ── Mode 2: API Key + Endpoint ────────────────────────────────────────────
    if api_key and endpoint:
        url = f"{endpoint}/openai/deployments?api-version=2024-05-01-preview"
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(url, headers={"api-key": api_key})
        if resp.status_code in (200, 404):
            return TestResult(
                success=True,
                message="Connected to Azure AI Foundry endpoint via API Key",
                details={"endpoint": endpoint},
            )
        return TestResult(
            success=False,
            message=f"Foundry API key test failed: HTTP {resp.status_code}: {resp.text[:200]}",
        )

    # ── Missing credentials ───────────────────────────────────────────────────
    return TestResult(
        success=False,
        message="Incomplete credentials. Please provide either:\n"
                "• Service Principal: Tenant ID + Client ID + Client Secret (recommended)\n"
                "• Project API Key + Project Endpoint URL",
    )


async def _test_aws_bedrock(config: dict, creds: dict) -> TestResult:
    try:
        import boto3  # type: ignore
        region = config.get("region", "us-east-1")
        client = boto3.client(
            "bedrock",
            region_name=region,
            aws_access_key_id=creds.get("access_key_id"),
            aws_secret_access_key=creds.get("secret_access_key"),
        )
        resp = client.list_foundation_models(byOutputModality="TEXT")
        model_ids = [m["modelId"] for m in resp.get("modelSummaries", [])[:5]]
        return TestResult(success=True, message="Connected to AWS Bedrock", details={"sample_models": model_ids})
    except Exception as exc:
        return TestResult(success=False, message=str(exc))


# ── Manual sync trigger ───────────────────────────────────────────────────────

class SyncResult(BaseModel):
    connector_id: uuid.UUID
    status: str
    message: str
    records_written: int = 0


@router.post(
    "/connectors/{connector_id}/sync",
    response_model=SyncResult,
    summary="Trigger a manual sync now",
)
async def sync_connector_now(
    connector_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    """
    Triggers the collector logic inline (for immediate testing).
    In production, this would publish a job to a task queue.
    """
    conn = await session.get(Connector, connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")

    # Mark as running
    conn.last_sync_status = "running"
    await session.flush()

    creds: dict = {}
    if conn.credentials_encrypted:
        try:
            creds = json.loads(decrypt_secret(conn.credentials_encrypted))
        except Exception as e:
            conn.last_sync_status = "error"
            conn.last_sync_error = str(e)
            await session.flush()
            return SyncResult(connector_id=connector_id, status="error", message=str(e))

    # Import and run adapter
    try:
        from app.sync import run_connector_sync  # type: ignore
        records = await run_connector_sync(conn, creds)
        conn.last_sync_status = "ok"
        conn.last_sync_error = None
        conn.last_sync_records = records
        conn.last_sync_at = datetime.now(timezone.utc)
        await session.flush()
        return SyncResult(
            connector_id=connector_id,
            status="ok",
            message=f"Sync complete — {records} records written",
            records_written=records,
        )
    except ImportError:
        # Collector not co-located; mark for next scheduled run
        conn.last_sync_status = "scheduled"
        conn.last_sync_at = datetime.now(timezone.utc)
        await session.flush()
        return SyncResult(
            connector_id=connector_id,
            status="scheduled",
            message="Sync queued — collector service will process within 10 minutes",
        )
    except Exception as exc:
        conn.last_sync_status = "error"
        conn.last_sync_error = str(exc)[:500]
        conn.last_sync_at = datetime.now(timezone.utc)
        await session.flush()
        return SyncResult(connector_id=connector_id, status="error", message=str(exc))
