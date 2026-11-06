"""
trustai/client.py
TrustAI SDK client — manages project context, batching, and export.
Developers call trustai.init() once, then use @trustai.trace / @trustai.llm_call.
"""
import asyncio
import atexit
import logging
import threading
import time
import uuid
from typing import Any

import httpx

from trustai.models import ContentCaptureMode, Span

logger = logging.getLogger("trustai.sdk")


class TrustAIClient:
    """
    Thread-safe SDK client with background flush.

    Typical usage (one client per process):
        trustai.init(api_key="tai_live_xxx", project_id="...", environment="prod")
    """

    def __init__(
        self,
        api_key: str,
        project_id: str,
        environment: str = "production",
        ingest_url: str = "http://localhost:8001",
        batch_size: int = 50,
        flush_interval_seconds: float = 5.0,
        content_capture_mode: ContentCaptureMode = "masked",
        sdk_version: str = "0.1.0",
        agent_name: str | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.project_id = project_id
        self.environment = environment
        self.ingest_url = ingest_url.rstrip("/")
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self.content_capture_mode: ContentCaptureMode = content_capture_mode
        self.sdk_version = sdk_version
        self.agent_name = agent_name
        self.timeout = timeout_seconds
        self.max_retries = max_retries

        self._buffer: list[Span] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(target=self._background_flush, daemon=True)
        self._flush_thread.start()
        atexit.register(self.flush)

        logger.info(
            "TrustAI SDK initialised | project=%s env=%s endpoint=%s",
            project_id,
            environment,
            ingest_url,
        )

    # ── Span Lifecycle ────────────────────────────────────────────

    def start_span(
        self,
        name: str,
        kind: str = "internal",
        parent_span_id: str | None = None,
        trace_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Span:
        span = Span(
            trace_id=trace_id or uuid.uuid4().hex,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent_span_id,
            span_name=name,
            span_kind=kind,  # type: ignore[arg-type]
            content_capture_mode=self.content_capture_mode,
            tags=tags or {},
        )
        return span

    def finish_span(
        self,
        span: Span,
        *,
        success: bool = True,
        error: Exception | None = None,
        input_content: str | None = None,
        output_content: str | None = None,
    ) -> None:
        span.finish(success=success, error=error)

        if self.content_capture_mode == "full":
            span.input_content = input_content
            span.output_content = output_content
        elif self.content_capture_mode == "masked":
            span.input_content = _mask_content(input_content)
            span.output_content = _mask_content(output_content)
        # else: "disabled" → content fields stay None

        with self._lock:
            self._buffer.append(span)
            if len(self._buffer) >= self.batch_size:
                self._drain()

    # ── Flushing ──────────────────────────────────────────────────

    def flush(self) -> None:
        """Synchronously flush all buffered spans."""
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()
        self._send_batch(batch)

    def shutdown(self) -> None:
        """Flush and stop the background thread."""
        self._stop_event.set()
        self.flush()

    def _background_flush(self) -> None:
        while not self._stop_event.wait(self.flush_interval):
            with self._lock:
                self._drain()

    def _drain(self) -> None:
        """Must be called while holding self._lock."""
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        # Fire-and-forget in a daemon thread
        threading.Thread(target=self._send_batch, args=(batch,), daemon=True).start()

    def _send_batch(self, spans: list[Span]) -> None:
        payload = {
            "project_id": self.project_id,
            "environment": self.environment,
            "agent_name": self.agent_name,
            "sdk_version": self.sdk_version,
            "spans": [s.to_ingest_dict() for s in spans],
        }
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        f"{self.ingest_url}/v1/traces",
                        json=payload,
                        headers={"X-API-Key": self.api_key},
                    )
                    resp.raise_for_status()
                    logger.debug("Flushed %d spans (attempt %d)", len(spans), attempt)
                    return
            except Exception as exc:
                logger.warning("Flush attempt %d/%d failed: %s", attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
        logger.error("Failed to flush %d spans after %d attempts — spans dropped", len(spans), self.max_retries)


# ── Simple PII Masking ────────────────────────────────────────────

import re

_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "[CARD]"),
    (re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
]


def _mask_content(text: str | None) -> str | None:
    if not text:
        return text
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
