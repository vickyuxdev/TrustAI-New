"""
trustai/connectors/base.py
Abstract connector interface for pulling telemetry from cloud providers.
Implement this interface to add any new provider (AWS, Databricks, etc.)
without changing any other TrustAI component.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from trustai.models import Span


class ConnectorConfig(dict):
    """Typed dict for connector configuration. Extend per provider."""
    pass


class BaseConnector(ABC):
    """
    Provider-neutral telemetry connector interface.

    TrustAI supports two ingestion modes:
      1. PUSH — SDK sends spans directly to the Ingestion Service (no connector needed).
      2. PULL — A connector periodically fetches raw telemetry from a cloud provider
                 and normalises it into TrustAI Span objects.

    This interface is for PULL-mode connectors.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name, e.g., 'azure_app_insights'."""
        ...

    @abstractmethod
    async def validate_config(self) -> bool:
        """
        Test connectivity to the provider using configured credentials.
        Returns True if successful, raises ConnectorError otherwise.
        """
        ...

    @abstractmethod
    async def fetch_raw_spans(
        self,
        since: datetime,
        until: datetime | None = None,
        project_filter: list[str] | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        """
        Fetch raw telemetry records from the provider in their native format.
        Returns a list of raw dicts (provider-specific schema).
        """
        ...

    @abstractmethod
    async def normalise(self, raw_spans: list[dict[str, Any]]) -> list[Span]:
        """
        Normalise provider-specific raw spans into TrustAI's provider-neutral
        Span model. This is the core transformation each connector must implement.
        """
        ...

    async def fetch_and_normalise(
        self,
        since: datetime,
        until: datetime | None = None,
        project_filter: list[str] | None = None,
    ) -> list[Span]:
        """Convenience: fetch then normalise in one call."""
        raw = await self.fetch_raw_spans(since, until, project_filter)
        return await self.normalise(raw)


class ConnectorError(Exception):
    """Raised when a connector fails to connect or normalise data."""
    def __init__(self, provider: str, message: str, cause: Exception | None = None):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.cause = cause
