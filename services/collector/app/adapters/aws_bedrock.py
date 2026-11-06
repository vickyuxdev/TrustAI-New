"""
services/collector/app/adapters/aws_bedrock.py
Pulls token usage and invocation metrics from AWS Bedrock via CloudWatch + Cost Explorer.

Required config:
  region            - AWS region, e.g. "us-east-1"
  account_id        - AWS account ID (for Cost Explorer)

Required credentials:
  access_key_id     - AWS Access Key ID
  secret_access_key - AWS Secret Access Key
"""
from datetime import datetime, timedelta, timezone

import structlog

from app.adapters.base import BaseAdapter
from app.models import ConnectorMetric

log = structlog.get_logger()

# Bedrock model ID → pricing (USD per 1M tokens, approximate)
_BEDROCK_PRICING: dict[str, tuple[float, float]] = {
    "anthropic.claude-3-5-sonnet-20241022-v2:0": (3.0, 15.0),
    "anthropic.claude-3-haiku-20240307-v1:0": (0.25, 1.25),
    "amazon.titan-text-premier-v1:0": (0.5, 1.5),
    "meta.llama3-70b-instruct-v1:0": (0.99, 0.99),
    "mistral.mistral-large-2402-v1:0": (4.0, 12.0),
}


def _get_pricing(model_id: str) -> tuple[float, float]:
    for key, price in _BEDROCK_PRICING.items():
        if key in model_id or model_id in key:
            return price
    return (1.0, 3.0)  # default fallback


class AWSBedrockAdapter(BaseAdapter):
    provider_name = "aws_bedrock"

    def _boto_client(self, service: str):
        import boto3  # type: ignore
        return boto3.client(
            service,
            region_name=self.config.get("region", "us-east-1"),
            aws_access_key_id=self.credentials.get("access_key_id"),
            aws_secret_access_key=self.credentials.get("secret_access_key"),
        )

    async def fetch(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        import asyncio
        loop = asyncio.get_event_loop()

        metrics: list[ConnectorMetric] = []

        # Run boto3 (sync) calls in executor to not block event loop
        try:
            cw_metrics = await loop.run_in_executor(
                None, self._fetch_cloudwatch, connector_id, client_id, project_id, since, until
            )
            metrics.extend(cw_metrics)
        except Exception as exc:
            log.error("aws_bedrock.cloudwatch_failed", connector_id=connector_id, error=str(exc))

        try:
            cost_metrics = await loop.run_in_executor(
                None, self._fetch_cost_explorer, connector_id, client_id, project_id, since, until
            )
            metrics.extend(cost_metrics)
        except Exception as exc:
            log.warning("aws_bedrock.cost_explorer_failed", connector_id=connector_id, error=str(exc))

        return metrics

    def _fetch_cloudwatch(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """Pull Bedrock invocation and token metrics from CloudWatch."""
        cw = self._boto_client("cloudwatch")
        region = self.config.get("region", "us-east-1")

        metric_names = [
            "Invocations",
            "InputTokenCount",
            "OutputTokenCount",
            "InvocationLatency",
            "InvocationClientErrors",
            "InvocationServerErrors",
        ]

        results: list[ConnectorMetric] = []

        # Get all model IDs that have data (list Bedrock foundation models)
        try:
            bedrock = self._boto_client("bedrock")
            models_resp = bedrock.list_foundation_models(byOutputModality="TEXT")
            model_ids = [m["modelId"] for m in models_resp.get("modelSummaries", [])]
        except Exception:
            model_ids = ["*"]  # try without dimension filter

        # Aggregate across all models
        all_input_tokens = 0
        all_output_tokens = 0
        all_invocations = 0
        all_errors = 0
        total_latency_sum = 0.0
        latency_count = 0

        for metric_name in metric_names:
            try:
                resp = cw.get_metric_statistics(
                    Namespace="AWS/Bedrock",
                    MetricName=metric_name,
                    StartTime=since,
                    EndTime=until,
                    Period=int((until - since).total_seconds()),
                    Statistics=["Sum", "Average"],
                )
                datapoints = resp.get("Datapoints", [])
                if not datapoints:
                    continue

                total = sum(dp.get("Sum", 0) for dp in datapoints)
                avg = sum(dp.get("Average", 0) for dp in datapoints) / len(datapoints)

                if metric_name == "InputTokenCount":
                    all_input_tokens = int(total)
                elif metric_name == "OutputTokenCount":
                    all_output_tokens = int(total)
                elif metric_name == "Invocations":
                    all_invocations = int(total)
                elif metric_name in ("InvocationClientErrors", "InvocationServerErrors"):
                    all_errors += int(total)
                elif metric_name == "InvocationLatency":
                    total_latency_sum += avg
                    latency_count += 1
            except Exception as e:
                log.debug("aws_bedrock.metric_skip", metric=metric_name, error=str(e))

        if all_invocations == 0 and all_input_tokens == 0:
            return []

        in_price, out_price = _get_pricing("amazon.bedrock")
        cost = (all_input_tokens / 1_000_000 * in_price) + (all_output_tokens / 1_000_000 * out_price)
        avg_lat = (total_latency_sum / latency_count) if latency_count > 0 else None

        results.append(ConnectorMetric(
            connector_id=connector_id,
            client_id=client_id,
            project_id=project_id,
            provider=self.provider_name,
            source=f"aws_bedrock:cloudwatch:{region}",
            period_start=since,
            period_end=until,
            model_name="aws_bedrock_aggregate",
            region=region,
            input_tokens=all_input_tokens,
            output_tokens=all_output_tokens,
            total_tokens=all_input_tokens + all_output_tokens,
            total_calls=all_invocations,
            failed_calls=all_errors,
            cost_usd=round(cost, 6),
            avg_latency_ms=avg_lat,
        ))
        return results

    def _fetch_cost_explorer(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """Pull actual billed cost for Bedrock from AWS Cost Explorer."""
        ce = self._boto_client("ce")

        resp = ce.get_cost_and_usage(
            TimePeriod={
                "Start": since.strftime("%Y-%m-%d"),
                "End": until.strftime("%Y-%m-%d"),
            },
            Granularity="DAILY",
            Filter={"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Bedrock"]}},
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        )

        total_cost = 0.0
        breakdown: dict = {}
        for result in resp.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                usage_type = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                total_cost += amount
                breakdown[usage_type] = breakdown.get(usage_type, 0) + amount

        if total_cost == 0:
            return []

        return [ConnectorMetric(
            connector_id=connector_id,
            client_id=client_id,
            project_id=project_id,
            provider=self.provider_name,
            source=f"aws_bedrock:cost_explorer",
            period_start=since,
            period_end=until,
            model_name="aws_bedrock_billing",
            cost_usd=round(total_cost, 6),
            extra={"cost_breakdown": breakdown},
        )]
