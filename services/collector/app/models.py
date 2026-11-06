"""services/collector/app/models.py — Normalised connector metric record."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConnectorMetric:
    """
    A single normalised metric record from any cloud provider.
    Maps to a row in the spans or daily_rollups table.
    """
    connector_id: str           # UUID of the Connector
    client_id: str              # UUID of Client
    project_id: str | None      # UUID of Project (optional)
    provider: str               # "azure_openai", "aws_bedrock", etc.
    source: str                 # e.g. "azure_openai:gpt-4o:eastus"

    # Time window this metric covers
    period_start: datetime
    period_end: datetime

    # LLM dimensions
    model_name: str | None = None
    deployment_name: str | None = None
    region: str | None = None

    # Metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_calls: int = 0
    failed_calls: int = 0
    cost_usd: float = 0.0
    avg_latency_ms: float | None = None
    p99_latency_ms: float | None = None

    # Extra provider-specific data (free-form)
    extra: dict = field(default_factory=dict)
