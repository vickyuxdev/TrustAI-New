"""services/collector/app/adapters/base.py — Abstract connector adapter."""
from abc import ABC, abstractmethod
from datetime import datetime

from app.models import ConnectorMetric


class BaseAdapter(ABC):
    """
    Each cloud provider implements this interface.
    `fetch` is called every sync_interval_minutes.
    """

    def __init__(self, config: dict, credentials: dict):
        self.config = config
        self.credentials = credentials

    @abstractmethod
    async def fetch(
        self,
        connector_id: str,
        client_id: str,
        project_id: str | None,
        since: datetime,
        until: datetime,
    ) -> list[ConnectorMetric]:
        """
        Pull metrics from the cloud provider for the given time window.
        Returns a list of normalised ConnectorMetric objects.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """String identifier for this provider."""
        ...
