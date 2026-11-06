"""
trustai/__init__.py
Public SDK API surface. Import and use:

    import trustai

    trustai.init(api_key="tai_live_xxx", project_id="...", environment="prod")

    @trustai.agent("my_agent")
    def run_agent(...): ...

    @trustai.llm_call(model="gpt-4o")
    def call_llm(client, messages): ...

    with trustai.span("custom_step") as sp:
        sp.tags["key"] = "value"
        do_work()
"""
from trustai.client import TrustAIClient
from trustai.decorators import _client as _active_client
from trustai.decorators import agent, llm_call, span, trace
from trustai.models import LLMUsage, Span

import trustai.decorators as _decorators

__version__ = "0.1.0"
__all__ = ["init", "shutdown", "flush", "trace", "agent", "llm_call", "span", "Span", "LLMUsage"]


def init(
    api_key: str,
    project_id: str,
    environment: str = "production",
    ingest_url: str = "http://localhost:8001",
    content_capture_mode: str = "masked",
    agent_name: str | None = None,
    batch_size: int = 50,
    flush_interval_seconds: float = 5.0,
    **kwargs,
) -> TrustAIClient:
    """
    Initialise the TrustAI SDK. Call this once at application startup.

    Args:
        api_key:               Project API key (generate in TrustAI dashboard).
        project_id:            Project UUID from TrustAI dashboard.
        environment:           "development", "staging", or "production".
        ingest_url:            URL of the TrustAI Ingestion Service.
        content_capture_mode:  "full" | "masked" | "disabled".
                               Can be overridden per-call via @trustai.llm_call.
        agent_name:            Default agent name for spans in this process.
        batch_size:            Max spans per batch flush.
        flush_interval_seconds: How often to auto-flush the buffer.

    Returns:
        The configured TrustAIClient (also stored globally for decorators).
    """
    client = TrustAIClient(
        api_key=api_key,
        project_id=project_id,
        environment=environment,
        ingest_url=ingest_url,
        content_capture_mode=content_capture_mode,  # type: ignore[arg-type]
        agent_name=agent_name,
        batch_size=batch_size,
        flush_interval_seconds=flush_interval_seconds,
        **kwargs,
    )
    _decorators._client = client
    return client


def flush() -> None:
    """Manually flush all buffered spans to the Ingestion Service."""
    if _decorators._client:
        _decorators._client.flush()


def shutdown() -> None:
    """Flush and cleanly shut down the SDK background thread."""
    if _decorators._client:
        _decorators._client.shutdown()
