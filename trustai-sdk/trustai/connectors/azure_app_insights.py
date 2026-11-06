"""
trustai/connectors/azure_app_insights.py
Azure Application Insights connector — pulls GenAI telemetry via the
Log Analytics REST API and normalises it into TrustAI Span objects.

This connector reads the same traces that tracing_utils.py (or the
AIProjectInstrumentor) writes to Application Insights, and brings them
into TrustAI's analytics database.
"""
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from trustai.connectors.base import BaseConnector, ConnectorError
from trustai.models import LLMUsage, Span

logger = logging.getLogger(__name__)

# KQL query that fetches GenAI spans from App Insights dependencies, requests, and customEvents
_GENAI_SPANS_KQL = """
let start = datetime({start});
let end   = datetime({end});
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
| take {limit}
"""


class AzureAppInsightsConnector(BaseConnector):
    """
    Pulls GenAI telemetry from Azure Application Insights via Log Analytics
    REST API and normalises it into provider-neutral TrustAI Spans.
    """

    def __init__(
        self,
        workspace_id: str,
        api_key: str | None = None,
        credential: Any | None = None,  # azure.identity credential object
    ):
        """
        Args:
            workspace_id: Log Analytics workspace ID (GUID).
            api_key: Log Analytics API key (for simple key-based access).
            credential: Azure Identity credential (DefaultAzureCredential etc.)
                        Takes precedence over api_key if both are provided.
        """
        self.workspace_id = workspace_id
        self._api_key = api_key
        self._credential = credential
        self._base_url = (
            f"https://api.loganalytics.io/v1/workspaces/{workspace_id}/query"
        )

    @property
    def provider_name(self) -> str:
        return "azure_app_insights"

    async def _get_auth_headers(self) -> dict[str, str]:
        if self._credential:
            # Use Azure Identity token
            token = self._credential.get_token(
                "https://api.loganalytics.io/.default"
            )
            return {"Authorization": f"Bearer {token.token}"}
        elif self._api_key:
            return {"x-api-key": self._api_key}
        raise ConnectorError(self.provider_name, "No credentials configured")

    async def validate_config(self) -> bool:
        """Run a trivial KQL query to confirm connectivity."""
        kql = "traces | take 1 | project timestamp"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = await self._get_auth_headers()
                resp = await client.post(
                    self._base_url,
                    headers=headers,
                    json={"query": kql},
                )
                resp.raise_for_status()
                return True
        except Exception as exc:
            raise ConnectorError(self.provider_name, "Connectivity check failed", exc) from exc

    async def fetch_raw_spans(
        self,
        since: datetime,
        until: datetime | None = None,
        project_filter: list[str] | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        until = until or datetime.now(timezone.utc)
        kql = _GENAI_SPANS_KQL.format(
            start=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            limit=limit,
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                headers = await self._get_auth_headers()
                resp = await client.post(
                    self._base_url,
                    headers=headers,
                    json={"query": kql},
                )
                resp.raise_for_status()
                data = resp.json()

            tables = data.get("tables", [])
            if not tables:
                return []

            table = tables[0]
            columns = [c["name"] for c in table["columns"]]
            rows = table["rows"]
            return [dict(zip(columns, row)) for row in rows]

        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                self.provider_name, f"Failed to fetch spans: {exc}", exc
            ) from exc

    async def normalise(self, raw_spans: list[dict[str, Any]]) -> list[Span]:
        """
        Transform App Insights raw rows into TrustAI Span objects.
        Maps customDimensions (gen_ai.* OTEL attributes) to Span fields.
        """
        spans: list[Span] = []
        for row in raw_spans:
            dims: dict[str, Any] = {}
            raw_dims = row.get("customDimensions")
            if isinstance(raw_dims, dict):
                dims = raw_dims
            elif isinstance(raw_dims, str):
                import json
                try:
                    dims = json.loads(raw_dims)
                except Exception:
                    dims = {}

            # Parse timestamp
            ts_str = row.get("timestamp", "")
            try:
                started_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                started_at = datetime.now(timezone.utc)

            duration_ms = row.get("duration_ms")

            usage = LLMUsage(
                input_tokens=_int(dims.get("gen_ai.usage.input_tokens")),
                output_tokens=_int(dims.get("gen_ai.usage.output_tokens")),
                total_tokens=_int(dims.get("gen_ai.usage.total_tokens")),
                cached_tokens=_int(dims.get("gen_ai.usage.cached_tokens")),
                cost_usd=_float(dims.get("cost_usd")),
            )

            span = Span(
                trace_id=row.get("trace_id", ""),
                span_id=row.get("span_id", ""),
                parent_span_id=row.get("parent_id") or None,
                span_name=row.get("span_name", "unknown"),
                span_kind=_infer_kind(dims),
                started_at=started_at,
                duration_ms=float(duration_ms) if duration_ms is not None else None,
                provider=dims.get("gen_ai.system", "azure_openai"),
                model_name=dims.get("gen_ai.request.model") or dims.get("gen_ai.response.model"),
                operation=dims.get("gen_ai.operation.name"),
                usage=usage,
                success=bool(row.get("success", True)),
                finish_reason=str(dims.get("gen_ai.response.finish_reasons", "")) or None,
                attributes=dims,
            )
            spans.append(span)
        return spans


# ── Helpers ──────────────────────────────────────────────────────

def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _infer_kind(dims: dict[str, Any]) -> str:
    system = dims.get("gen_ai.system", "")
    if system:
        return "llm"
    op = dims.get("gen_ai.operation.name", "")
    if "embed" in op:
        return "llm"
    return "internal"
