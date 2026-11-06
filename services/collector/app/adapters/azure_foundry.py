"""
services/collector/app/adapters/azure_foundry.py

Pulls inference metrics and token usage from Azure AI Foundry using:
  1. AIProjectClient (azure-ai-projects SDK) — Service Principal / Entra ID auth
  2. Azure Monitor REST API — aggregate token metrics via resource_id
  3. Foundry OpenAI-compatible /deployments endpoint — deployment inventory

Auth methods supported (in priority order):
  a. Service Principal  (tenant_id + client_id + client_secret)  ← recommended
  b. API Key            (api_key field in credentials)            ← fallback

Required config  (connector.config JSONB):
  endpoint          - https://<resource>.services.ai.azure.com/api/projects/<project>
  api_version       - e.g. "2024-05-01-preview"
  resource_id       - full Azure resource ID for Monitor queries (optional but recommended)
                      /subscriptions/<sub>/resourceGroups/<rg>/providers/
                      Microsoft.CognitiveServices/accounts/<hub>

Required credentials  (connector.credentials JSONB, encrypted at rest):
  tenant_id         - Azure Tenant / Directory ID
  client_id         - Service Principal App (Client) ID
  client_secret     - Service Principal secret

  OR (fallback):
  api_key           - Foundry project API key
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import structlog

from app.adapters.base import BaseAdapter
from app.models import ConnectorMetric

log = structlog.get_logger()


def _build_credential(credentials: dict):
    """
    Build an Azure credential object.
    Prefer Service Principal; fall back to nothing (caller must use api_key).
    """
    tenant_id     = credentials.get("tenant_id", "").strip()
    client_id     = credentials.get("client_id", "").strip()
    client_secret = credentials.get("client_secret", "").strip()

    if tenant_id and client_id and client_secret:
        from azure.identity import ClientSecretCredential
        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
    return None


class AzureFoundryAdapter(BaseAdapter):
    provider_name = "azure_foundry"

    # ── public entry-point ────────────────────────────────────────────────────
    async def fetch(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        metrics: list[ConnectorMetric] = []

        # 1. Deployment-level metrics via AIProjectClient (preferred)
        try:
            metrics.extend(
                await self._fetch_via_project_client(connector_id, client_id, project_id, since, until)
            )
        except Exception as exc:
            log.warning("azure_foundry.project_client_failed", connector_id=connector_id, error=str(exc))

        # 2. Aggregate token metrics from Azure Monitor (if resource_id configured)
        if self.config.get("resource_id"):
            try:
                metrics.extend(
                    await self._fetch_from_monitor(connector_id, client_id, project_id, since, until)
                )
            except Exception as exc:
                log.debug("azure_foundry.monitor_skip", connector_id=connector_id, error=str(exc))

        # 3. Fallback: OpenAI-compatible deployments list via API key
        if not metrics:
            try:
                metrics.extend(
                    await self._fetch_deployments_apikeyonly(connector_id, client_id, project_id, since, until)
                )
            except Exception as exc:
                log.error("azure_foundry.fallback_failed", connector_id=connector_id, error=str(exc))

        return metrics

    # ── Method 1: AIProjectClient (Service Principal auth) ────────────────────
    async def _fetch_via_project_client(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """
        Use azure-ai-projects AIProjectClient with ClientSecretCredential.
        Mirrors the pattern in the R&D foundry_connector.py:
          project_client = AIProjectClient(endpoint=..., credential=...)
          openai_client  = project_client.get_openai_client()

        We don't make live calls — we list deployments and capture metadata.
        Token/cost metrics come from Azure Monitor (method 2).
        """
        from azure.ai.projects import AIProjectClient as _AIProjClient

        endpoint   = self.config.get("endpoint", "").rstrip("/")
        credential = _build_credential(self.credentials)

        if not endpoint or not credential:
            return []

        log.info("azure_foundry.connecting_via_project_client", endpoint=endpoint)

        # Initialise AIProjectClient (matches R&D foundry_connector.py exactly)
        project_client = _AIProjClient(
            endpoint=endpoint,
            credential=credential,
            logging_enable=False,
        )

        results: list[ConnectorMetric] = []

        # List connections / deployments available in this Foundry project
        try:
            connections = list(project_client.connections.list())
            log.info("azure_foundry.connections_found", count=len(connections))
            for conn in connections:
                conn_name = getattr(conn, "name", "unknown")
                conn_type = getattr(conn, "connection_type", "unknown")
                results.append(ConnectorMetric(
                    connector_id=connector_id,
                    client_id=client_id,
                    project_id=project_id,
                    provider=self.provider_name,
                    source=f"azure_foundry:connection:{conn_name}",
                    period_start=since,
                    period_end=until,
                    model_name=conn_name,
                    extra={
                        "connection_type": str(conn_type),
                        "endpoint": endpoint,
                        "auth_method": "service_principal",
                    },
                ))
        except Exception as exc:
            log.debug("azure_foundry.connections_list_failed", error=str(exc))

        # Also try listing model deployments via the OpenAI-compatible client
        try:
            openai_client = project_client.get_openai_client()
            dep_resp = openai_client.models.list()
            for model in dep_resp.data:
                model_id = getattr(model, "id", "unknown")
                results.append(ConnectorMetric(
                    connector_id=connector_id,
                    client_id=client_id,
                    project_id=project_id,
                    provider=self.provider_name,
                    source=f"azure_foundry:deployment:{model_id}",
                    period_start=since,
                    period_end=until,
                    model_name=model_id,
                    deployment_name=model_id,
                    extra={
                        "object": getattr(model, "object", ""),
                        "endpoint": endpoint,
                        "auth_method": "service_principal",
                    },
                ))
        except Exception as exc:
            log.debug("azure_foundry.models_list_failed", error=str(exc))

        return results

    # ── Method 2: Azure Monitor aggregate token metrics ───────────────────────
    async def _fetch_from_monitor(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """
        Query Azure Monitor for aggregate token metrics.
        Requires resource_id in config and Service Principal credentials.
        """
        import asyncio

        raw_res = self.config.get("resource_id", "")
        if "/subscriptions/" in raw_res:
            resource_id = "/subscriptions/" + raw_res.split("/subscriptions/")[1].split("/overview")[0].split("?")[0].rstrip("/")
        else:
            resource_id = raw_res.strip()

        credential = _build_credential(self.credentials)

        if not resource_id or not credential:
            return []

        from azure.monitor.query import MetricsQueryClient, MetricAggregationType

        def _query():
            monitor = MetricsQueryClient(credential)
            return monitor.query_resource(
                resource_id,
                metric_names=[
                    "TokenTransaction",
                    "ProcessedPromptTokens",
                    "GeneratedCompletionTokens",
                ],
                timespan=(since, until),
                granularity=timedelta(hours=1),
                aggregations=[MetricAggregationType.TOTAL],
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _query)

        totals: dict[str, float] = {}
        for m in response.metrics:
            totals[m.name] = sum(dp.total or 0 for ts in m.timeseries for dp in ts.data)

        input_t  = int(totals.get("ProcessedPromptTokens", 0))
        output_t = int(totals.get("GeneratedCompletionTokens", 0))
        total_t  = int(totals.get("TokenTransaction", input_t + output_t))

        if total_t == 0:
            return []

        # Standard GPT-4o pricing as default (can be refined per deployment)
        cost = round((input_t / 1_000_000 * 2.50) + (output_t / 1_000_000 * 10.0), 6)

        return [ConnectorMetric(
            connector_id=connector_id,
            client_id=client_id,
            project_id=project_id,
            provider=self.provider_name,
            source=f"azure_foundry:monitor:{resource_id.split('/')[-1]}",
            period_start=since,
            period_end=until,
            model_name="azure_foundry_aggregate",
            input_tokens=input_t,
            output_tokens=output_t,
            total_tokens=total_t,
            cost_usd=cost,
            extra={"auth_method": "service_principal", "resource_id_suffix": resource_id[-20:]},
        )]

    # ── Method 3: API-key-only fallback (deployments list) ───────────────────
    async def _fetch_deployments_apikeyonly(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """
        Fallback: hit the OpenAI-compatible endpoint with an API key.
        Only returns deployment inventory — no token metrics without Monitor.
        """
        import httpx

        # Support both Foundry project endpoint and plain OpenAI endpoint
        endpoint    = self.config.get("endpoint", "").rstrip("/")
        api_key     = self.credentials.get("api_key", "")
        api_version = self.config.get("api_version", "2024-05-01-preview")

        if not endpoint or not api_key:
            return []

        results: list[ConnectorMetric] = []

        async with httpx.AsyncClient(timeout=20) as http:
            try:
                dep_resp = await http.get(
                    f"{endpoint}/openai/deployments?api-version={api_version}",
                    headers={"api-key": api_key},
                )
                deployments = dep_resp.json().get("data", []) if dep_resp.status_code == 200 else []
            except Exception:
                deployments = []

            for dep in deployments:
                dep_id = dep.get("id", "unknown")
                model  = dep.get("model", "unknown")
                results.append(ConnectorMetric(
                    connector_id=connector_id,
                    client_id=client_id,
                    project_id=project_id,
                    provider=self.provider_name,
                    source=f"azure_foundry:apikey:{dep_id}",
                    period_start=since,
                    period_end=until,
                    model_name=model,
                    deployment_name=dep_id,
                    extra={
                        "status":   dep.get("status", "unknown"),
                        "capacity": dep.get("capacity"),
                        "sku":      dep.get("sku", {}),
                        "auth_method": "api_key",
                    },
                ))

        return results
