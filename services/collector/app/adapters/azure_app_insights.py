"""
services/collector/app/adapters/azure_app_insights.py
Pulls LLM traces/events from Azure Application Insights via Log Analytics REST API / App Insights REST API.

Supports:
  - Standard OpenTelemetry GenAI Semantic Conventions (azure-monitor-opentelemetry, AIProjectInstrumentor)
  - Custom spans from tracer.start_as_current_span()
  - Legacy customEvents ("llm_call", "trustai_span", "LLMCall")
  - Automatic token pricing calculation for popular LLMs (GPT-4o, GPT-4o-mini, etc.)
  - Both Log Analytics Workspace API Key and Azure AD OAuth2 Client Credentials authentication

Required config:
  workspace_id   - Log Analytics workspace GUID (or application_id)
  application_id - (optional, App Insights Application ID for AAD auth)

Required credentials:
  api_key        - Log Analytics API key (or use AAD via tenant_id/client_id/client_secret)
  tenant_id      - (optional, for AAD auth)
  client_id      - (optional, for AAD auth)
  client_secret  - (optional, for AAD auth)
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.adapters.base import BaseAdapter
from app.models import ConnectorMetric

log = structlog.get_logger()

# Estimated pricing per 1M tokens (USD)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00, "cached": 1.25},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached": 0.075},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00, "cached": 5.00},
    "gpt-4": {"input": 30.00, "output": 60.00, "cached": 15.00},
    "gpt-35-turbo": {"input": 0.50, "output": 1.50, "cached": 0.25},
    "o1-preview": {"input": 15.00, "output": 60.00, "cached": 7.50},
    "o1-mini": {"input": 3.00, "output": 12.00, "cached": 1.50},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0, "cached": 0.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0, "cached": 0.0},
}


def _estimate_cost_usd(model_name: str | None, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """Calculate estimated cost based on token counts and model pricing."""
    if not model_name:
        return round((input_tokens * 2.50 + output_tokens * 10.00) / 1_000_000, 6)

    m_lower = model_name.lower()
    # Sort keys by length descending so more specific names (e.g. gpt-4o-mini) match before gpt-4o
    for key in sorted(MODEL_PRICING.keys(), key=len, reverse=True):
        if key in m_lower:
            p = MODEL_PRICING[key]
            uncached_in = max(0, input_tokens - cached_tokens)
            cost = (
                (uncached_in * p["input"])
                + (cached_tokens * p.get("cached", p["input"]))
                + (output_tokens * p["output"])
            ) / 1_000_000
            return round(cost, 6)

    # Default fallback to gpt-4o rates
    return round((input_tokens * 2.50 + output_tokens * 10.00) / 1_000_000, 6)


_KQL_MULTI_SOURCE_SPANS = """
let start = datetime('{since}');
let end   = datetime('{until}');
union
  (dependencies
   | where timestamp between (start .. end)
   | where customDimensions has "gen_ai"
        or name in ("chat_completion_turn", "llm_call", "trustai_span", "LLMCall", "chat_tracker")
        or type startswith "GenAI"
        or target has "openai.azure.com"
        or type in ("InProc", "Azure OpenAI", "HTTP")
   | project
       timestamp,
       trace_id    = tostring(operation_Id),
       span_id     = tostring(id),
       parent_id   = tostring(operation_ParentId),
       span_name   = name,
       duration_ms = duration,
       success     = tobool(success),
       resultCode  = tostring(resultCode),
       customDimensions,
       item_type   = "dependency"
  ),
  (requests
   | where timestamp between (start .. end)
   | where customDimensions has "gen_ai"
        or name in ("chat_completion_turn", "llm_call", "trustai_span", "chat_tracker")
   | project
       timestamp,
       trace_id    = tostring(operation_Id),
       span_id     = tostring(id),
       parent_id   = tostring(operation_ParentId),
       span_name   = name,
       duration_ms = duration,
       success     = (resultCode == "200"),
       resultCode  = tostring(resultCode),
       customDimensions,
       item_type   = "request"
  ),
  (customEvents
   | where timestamp between (start .. end)
   | where name in ("llm_call", "trustai_span", "LLMCall", "chat_completion_turn", "gen_ai_turn", "chat_tracker")
        or customDimensions has "gen_ai"
   | project
       timestamp,
       trace_id    = coalesce(tostring(operation_Id), tostring(customDimensions["trace_id"]), tostring(id)),
       span_id     = coalesce(tostring(id), tostring(customDimensions["span_id"]), tostring(operation_Id)),
       parent_id   = tostring(operation_ParentId),
       span_name   = name,
       duration_ms = coalesce(todouble(customDimensions["duration_ms"]), todouble(customDimensions["duration"]), 0.0),
       success     = coalesce(tobool(customDimensions["success"]), true),
       resultCode  = "200",
       customDimensions,
       item_type   = "customEvent"
  )
| order by timestamp asc
"""

_KQL_EXCEPTIONS = """
exceptions
| where timestamp between (datetime('{since}') .. datetime('{until}'))
| summarize failed_calls = count() by bin(timestamp, 1h)
"""


class AzureAppInsightsAdapter(BaseAdapter):
    provider_name = "azure_app_insights"

    async def fetch_spans(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]]:
        """
        Extract individual LLM spans from Azure App Insights (dependencies, requests, customEvents)
        and normalise into SpanRecord-compatible dicts.
        """
        workspace_id = self.config.get("workspace_id") or self.config.get("application_id", "")
        if not workspace_id:
            log.warning("app_insights.missing_workspace_id", connector_id=connector_id)
            return []

        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        until_str = until.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            raw_rows = await self._query_kql(
                workspace_id,
                _KQL_MULTI_SOURCE_SPANS.format(since=since_str, until=until_str),
            )
        except Exception as exc:
            log.error("app_insights.fetch_spans_failed", connector_id=connector_id, error=str(exc))
            return []

        normalised_spans: list[dict[str, Any]] = []

        for row in raw_rows:
            dims: dict[str, Any] = {}
            raw_dims = row.get("customDimensions")
            if isinstance(raw_dims, dict):
                dims = raw_dims
            elif isinstance(raw_dims, str):
                try:
                    dims = json.loads(raw_dims)
                except Exception:
                    dims = {}

            # 1. Parse timestamps
            ts_str = row.get("timestamp", "")
            try:
                started_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                started_at = datetime.now(timezone.utc)

            dur_ms = row.get("duration_ms")
            duration_ms = float(dur_ms) if dur_ms is not None else 0.0
            ended_at = started_at + timedelta(milliseconds=duration_ms)

            # 2. Extract model name & provider
            model_name = (
                dims.get("gen_ai.request.model")
                or dims.get("gen_ai.response.model")
                or dims.get("model_name")
                or dims.get("model")
                or "gpt-4o"
            )
            provider = dims.get("gen_ai.system") or dims.get("provider") or "azure_openai"
            operation = dims.get("gen_ai.operation.name") or dims.get("operation") or "chat"

            # 3. Extract token usage
            input_tokens = _int_val(
                dims.get("gen_ai.usage.prompt_tokens")
                or dims.get("gen_ai.usage.input_tokens")
                or dims.get("prompt_tokens")
                or dims.get("input_tokens")
            ) or 0
            output_tokens = _int_val(
                dims.get("gen_ai.usage.completion_tokens")
                or dims.get("gen_ai.usage.output_tokens")
                or dims.get("completion_tokens")
                or dims.get("output_tokens")
            ) or 0
            cached_tokens = _int_val(
                dims.get("gen_ai.usage.cached_tokens")
                or dims.get("cached_tokens")
            ) or 0
            reasoning_tokens = _int_val(
                dims.get("gen_ai.usage.reasoning_tokens")
                or dims.get("reasoning_tokens")
            ) or 0
            total_tokens = _int_val(
                dims.get("gen_ai.usage.total_tokens")
                or dims.get("total_tokens")
            ) or (input_tokens + output_tokens)

            # 4. Extract or estimate cost
            cost_usd = _float_val(dims.get("cost_usd"))
            if cost_usd is None and (input_tokens or output_tokens):
                cost_usd = _estimate_cost_usd(model_name, input_tokens, output_tokens, cached_tokens)

            # 5. Extract prompt / completion content
            input_content = (
                dims.get("gen_ai.prompt")
                or dims.get("prompt")
                or dims.get("input")
                or dims.get("messages")
            )
            if isinstance(input_content, (dict, list)):
                input_content = json.dumps(input_content)

            output_content = (
                dims.get("gen_ai.response.completion")
                or dims.get("response")
                or dims.get("completion")
                or dims.get("output")
            )
            if isinstance(output_content, (dict, list)):
                output_content = json.dumps(output_content)

            # 6. Status & finish reasons
            success = bool(row.get("success", True))
            finish_reason = str(dims.get("gen_ai.response.finish_reasons") or dims.get("finish_reason") or "")
            if not finish_reason:
                finish_reason = "stop" if success else "error"

            trace_id = str(row.get("trace_id") or uuid.uuid4().hex)
            span_id = str(row.get("span_id") or uuid.uuid4().hex[:16])
            parent_span_id = str(row.get("parent_id")) if row.get("parent_id") else None

            span_dict = {
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "span_name": row.get("span_name", "chat_completion_turn"),
                "span_kind": "llm",
                "timestamp": started_at,
                "duration_ms": duration_ms,
                "started_at": started_at,
                "ended_at": ended_at,
                "provider": provider,
                "model_name": model_name,
                "operation": operation,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cached_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens,
                "cost_usd": cost_usd or 0.0,
                "input_content": str(input_content) if input_content else None,
                "output_content": str(output_content) if output_content else None,
                "content_capture_mode": "full" if (input_content or output_content) else "masked",
                "success": success,
                "error_type": str(dims.get("error_type", "")) or (None if success else "LLMError"),
                "error_message": str(dims.get("error") or dims.get("error_message") or "") or None,
                "finish_reason": finish_reason,
                "source_provider": "azure_app_insights",
                "raw_attributes": dims,
                "tags": {
                    "imported_from": "azure_app_insights",
                    "item_type": row.get("item_type", "dependency"),
                },
            }
            normalised_spans.append(span_dict)

        return normalised_spans

    async def fetch(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """
        Pull metrics and calculate rollups for the time window.
        """
        workspace_id = self.config.get("workspace_id") or self.config.get("application_id", "")
        if not workspace_id:
            log.warning("app_insights.missing_workspace_id", connector_id=connector_id)
            return []

        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        until_str = until.strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Fetch individual spans
        spans = await self.fetch_spans(connector_id, client_id, project_id, since, until)

        # 2. Fetch exception counts
        failed_calls = 0
        try:
            failed_rows = await self._query_kql(
                workspace_id,
                _KQL_EXCEPTIONS.format(since=since_str, until=until_str),
            )
            failed_calls = sum(r.get("failed_calls", 0) or 0 for r in failed_rows)
        except Exception as exc:
            log.warning("app_insights.exceptions_query_failed", error=str(exc))

        if not spans and failed_calls == 0:
            log.info("app_insights.no_data", connector_id=connector_id, since=since_str)
            return []

        # Group spans by model_name to produce accurate ConnectorMetric per model
        by_model: dict[str, list[dict[str, Any]]] = {}
        for s in spans:
            m = s.get("model_name") or "gpt-4o"
            by_model.setdefault(m, []).append(s)

        if not by_model:
            by_model["gpt-4o"] = []

        metrics: list[ConnectorMetric] = []
        for model_name, m_spans in by_model.items():
            total_input = sum(s.get("input_tokens", 0) or 0 for s in m_spans)
            total_output = sum(s.get("output_tokens", 0) or 0 for s in m_spans)
            total_cost = sum(s.get("cost_usd", 0.0) or 0.0 for s in m_spans)
            calls = len(m_spans)
            failed_in_spans = sum(1 for s in m_spans if not s.get("success", True))
            avg_latency = (
                sum(s.get("duration_ms", 0.0) or 0.0 for s in m_spans) / calls
                if calls > 0 else None
            )

            metrics.append(
                ConnectorMetric(
                    connector_id=connector_id,
                    client_id=client_id,
                    project_id=project_id,
                    provider=self.provider_name,
                    source=f"azure_app_insights:{workspace_id[:8]}",
                    period_start=since,
                    period_end=until,
                    model_name=model_name,
                    input_tokens=int(total_input),
                    output_tokens=int(total_output),
                    total_tokens=int(total_input + total_output),
                    total_calls=int(calls),
                    failed_calls=int(failed_in_spans or failed_calls),
                    cost_usd=round(float(total_cost), 6),
                    avg_latency_ms=float(avg_latency) if avg_latency else None,
                )
            )

        return metrics

    async def _query_kql(self, workspace_id: str, query: str) -> list[dict]:
        """Execute a KQL query against Log Analytics REST API or App Insights REST API."""
        api_key = self.credentials.get("api_key", "")
        tenant_id = self.credentials.get("tenant_id", "")
        client_id = self.credentials.get("client_id", "")
        client_secret = self.credentials.get("client_secret", "")
        application_id = self.config.get("application_id", "")

        import httpx

        headers: dict = {"Content-Type": "application/json"}

        # Determine target endpoint & auth mode
        if tenant_id and client_id and client_secret:
            if application_id:
                # Mode A: Application Insights REST API with AAD
                token = await self._get_aad_token(
                    tenant_id, client_id, client_secret, scope="https://api.applicationinsights.io/.default"
                )
                url = f"https://api.applicationinsights.io/v1/apps/{application_id}/query"
            else:
                # Mode B: Log Analytics REST API with AAD
                token = await self._get_aad_token(
                    tenant_id, client_id, client_secret, scope="https://api.loganalytics.io/.default"
                )
                url = f"https://api.loganalytics.io/v1/workspaces/{workspace_id}/query"
            headers["Authorization"] = f"Bearer {token}"
        elif api_key:
            # Mode C: Log Analytics API Key
            url = f"https://api.loganalytics.io/v1/workspaces/{workspace_id}/query"
            headers["x-api-key"] = api_key
        else:
            raise ValueError("No valid credentials configured for Azure Application Insights connector")

        async with httpx.AsyncClient(timeout=35) as client:
            resp = await client.post(url, json={"query": query}, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"KQL query failed: HTTP {resp.status_code} — {resp.text[:300]}")

        data = resp.json()
        tables = data.get("tables", [])
        if not tables:
            return []

        table = tables[0]
        columns = [c["name"] for c in table.get("columns", [])]
        return [dict(zip(columns, row)) for row in table.get("rows", [])]

    async def _get_aad_token(
        self, tenant_id: str, client_id: str, client_secret: str, scope: str = "https://api.loganalytics.io/.default"
    ) -> str:
        import httpx
        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, data=data)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to obtain AAD token: HTTP {resp.status_code} — {resp.text[:200]}")
        return resp.json()["access_token"]


def _int_val(v: Any) -> int | None:
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _float_val(v: Any) -> float | None:
    try:
        return float(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None

