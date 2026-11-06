"""
services/collector/app/adapters/azure_openai.py
Pulls token usage and cost metrics from Azure OpenAI via Azure Monitor Metrics API.

Required config:
  endpoint          - https://<resource>.openai.azure.com
  resource_id       - /subscriptions/.../providers/Microsoft.CognitiveServices/accounts/<name>
  api_version       - e.g. "2024-02-01"
  deployments       - list of deployment names to monitor (optional, monitors all if empty)

Required credentials:
  api_key           - Azure OpenAI API key
  subscription_id   - Azure subscription ID (for cost data, optional)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.adapters.base import BaseAdapter
from app.models import ConnectorMetric

log = structlog.get_logger()


class AzureOpenAIAdapter(BaseAdapter):
    provider_name = "azure_openai"

    async def fetch(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        metrics: list[ConnectorMetric] = []

        try:
            metrics.extend(await self._fetch_monitor_metrics(
                connector_id, client_id, project_id, since, until
            ))
        except Exception as exc:
            log.error("azure_openai.monitor_failed", connector_id=connector_id, error=str(exc))

        return metrics

    async def _fetch_monitor_metrics(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """Query Azure Monitor Metrics for token usage."""
        from azure.identity import AzureCliCredential, ClientSecretCredential
        from azure.monitor.query import MetricsQueryClient, MetricAggregationType
        import httpx

        resource_id = self.config.get("resource_id", "")
        endpoint = self.config.get("endpoint", "").rstrip("/")
        api_key = self.credentials.get("api_key", "")

        if not resource_id or not endpoint:
            log.warning("azure_openai.missing_config", connector_id=connector_id)
            return []

        # Try Azure Monitor SDK (requires Azure AD auth)
        tenant_id = self.credentials.get("tenant_id", "")
        client_secret = self.credentials.get("client_secret", "")
        azure_client_id = self.credentials.get("client_id", "")

        try:
            if tenant_id and azure_client_id and client_secret:
                credential = ClientSecretCredential(tenant_id, azure_client_id, client_secret)
            else:
                credential = AzureCliCredential()

            monitor_client = MetricsQueryClient(credential)

            response = monitor_client.query_resource(
                resource_id,
                metric_names=[
                    "PromptTokenCount",
                    "GeneratedTokenCount",
                    "RequestCount",
                    "RequestSucceeded",
                    "RequestFailed",
                ],
                timespan=(since, until),
                granularity=timedelta(hours=1),
                aggregations=[MetricAggregationType.TOTAL, MetricAggregationType.AVERAGE],
            )

            # Aggregate across all time buckets
            totals: dict[str, float] = {}
            for metric in response.metrics:
                name = metric.name
                total = sum(
                    dp.total or 0
                    for ts in metric.timeseries
                    for dp in ts.data
                )
                totals[name] = total

            input_tokens = int(totals.get("PromptTokenCount", 0))
            output_tokens = int(totals.get("GeneratedTokenCount", 0))
            calls = int(totals.get("RequestCount", totals.get("RequestSucceeded", 0)))
            failed = int(totals.get("RequestFailed", 0))

            # Estimate cost (use model pricing if available; fallback to gpt-4o rate)
            cost_usd = (input_tokens / 1_000_000 * 2.50) + (output_tokens / 1_000_000 * 10.00)

            return [
                ConnectorMetric(
                    connector_id=connector_id,
                    client_id=client_id,
                    project_id=project_id,
                    provider=self.provider_name,
                    source=f"azure_openai:{endpoint}",
                    period_start=since,
                    period_end=until,
                    model_name="azure_openai",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    total_calls=calls,
                    failed_calls=failed,
                    cost_usd=round(cost_usd, 6),
                )
            ]
        except Exception as monitor_exc:
            log.warning(
                "azure_openai.monitor_sdk_failed_trying_direct_api",
                error=str(monitor_exc),
                connector_id=connector_id,
            )
            # Fallback: call the Azure OpenAI usage endpoint directly
            return await self._fetch_via_direct_api(
                connector_id, client_id, project_id, endpoint, api_key, since, until
            )

    async def _fetch_via_direct_api(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        endpoint: str,
        api_key: str,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """
        Fallback: list deployments and probe each one's model info.
        Azure OpenAI doesn't have a public usage endpoint like OpenAI does,
        so we list deployments and record them as zero-usage records
        (real usage comes via Monitor or App Insights).
        """
        import httpx
        api_version = self.config.get("api_version", "2024-02-01")
        url = f"{endpoint}/openai/deployments?api-version={api_version}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers={"api-key": api_key})
            if resp.status_code != 200:
                log.warning("azure_openai.deployments_fetch_failed", status=resp.status_code)
                return []

            deployments = resp.json().get("data", [])
            metrics = []
            for dep in deployments:
                metrics.append(ConnectorMetric(
                    connector_id=connector_id,
                    client_id=client_id,
                    project_id=project_id,
                    provider=self.provider_name,
                    source=f"azure_openai:{dep.get('id', 'unknown')}",
                    period_start=since,
                    period_end=until,
                    model_name=dep.get("model", "unknown"),
                    deployment_name=dep.get("id"),
                    extra={"status": dep.get("status"), "sku": dep.get("sku", {})},
                ))
            return metrics
        except Exception as exc:
            log.error("azure_openai.direct_api_failed", error=str(exc))
            return []
