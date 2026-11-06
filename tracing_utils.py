"""
tracing_utils.py

Generic OpenTelemetry / Application Insights tracing helpers for
Azure OpenAI (and other) calls. Extracted so it can be dropped into
any project unchanged -- nothing in this file is specific to any one
document-extraction pipeline.

Usage
-----
    from tracing_utils import traced, run_traced, flush_traces

    @traced("my_step_tracker")
    def do_something(x, y):
        ...

    # or, for call sites that need a different span name per call:
    result = run_traced("chat_tracker", raw_llm_call, client, deployment,
                         is_llm=True, messages=[...])

    # at the end of a script / notebook cell:
    flush_traces()

Setup
-----
Set these before importing anything that creates spans (this module
sets the two AZURE_* env vars itself as soon as it's imported, so just
make sure this import happens before you import azure.ai.projects
anywhere in your app):

    APPLICATIONINSIGHTS_CONNECTION_STRING=...   # required to actually export
    AZURE_OPENAI_PRICE_INPUT_PER_1M=...          # optional, enables cost_usd
    AZURE_OPENAI_PRICE_OUTPUT_PER_1M=...         # optional, enables cost_usd
    AZURE_OPENAI_PRICE_CACHED_INPUT_PER_1M=...   # optional

If APPLICATIONINSIGHTS_CONNECTION_STRING isn't set, spans/metrics are
still created locally (and printed for LLM calls) but nothing is
exported anywhere.
"""

import os
import time
import json
import inspect
import logging
import functools
from typing import Any

# ============================================================
# Tracing setup (no FastAPI needed)
#
# AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING must be set before
# AIProjectInstrumentor().instrument() is called, which is why
# it's set immediately, before the azure.ai.projects import.
# ============================================================
os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
os.environ.setdefault("AZURE_TRACING_GEN_AI_ENABLE_TRACE_CONTEXT_PROPAGATION", "true")
# Attaches full prompt/response text to spans. Anyone with Log Analytics
# Reader on the App Insights resource can read it. Set to "false" via
# env var before import if that's not acceptable for your data.
os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

from azure.ai.projects.telemetry import AIProjectInstrumentor
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode

_APP_INSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

logger = logging.getLogger("tracing_utils")
logger.setLevel(logging.INFO)

if _APP_INSIGHTS_CONNECTION_STRING:
    configure_azure_monitor(connection_string=_APP_INSIGHTS_CONNECTION_STRING, enable_live_metrics=False)
else:
    logger.warning(
        "APPLICATIONINSIGHTS_CONNECTION_STRING not set -- spans/metrics "
        "will be created locally but not exported anywhere."
    )

# Auto-instruments openai_client.chat.completions.create(...) calls,
# creating a GenAI span for each one automatically.
AIProjectInstrumentor().instrument()

tracer = trace.get_tracer("tracing_utils")
meter = metrics.get_meter("tracing_utils")

gen_ai_token_usage_histogram = meter.create_histogram(
    name="gen_ai.client.token.usage",
    unit="{token}",
    description="Input/output tokens used per GenAI call.",
)
gen_ai_operation_duration_histogram = meter.create_histogram(
    name="gen_ai.client.operation.duration",
    unit="s",
    description="GenAI client operation duration.",
)


# ---------------- Token usage / cost helpers ----------------

def get_usage_value(usage: Any, name: str) -> Any:
    if isinstance(usage, dict):
        return usage.get(name)
    return getattr(usage, name, None)


def get_nested_usage_value(usage: Any, parent: str, child: str) -> Any:
    nested = get_usage_value(usage, parent)
    if not nested:
        return None
    if isinstance(nested, dict):
        return nested.get(child)
    return getattr(nested, child, None)


def _extract_token_counts(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    return {
        "input_tokens": get_usage_value(usage, "prompt_tokens"),
        "output_tokens": get_usage_value(usage, "completion_tokens"),
        "total_tokens": get_usage_value(usage, "total_tokens"),
        "cached_tokens": get_nested_usage_value(usage, "prompt_tokens_details", "cached_tokens"),
        "reasoning_tokens": get_nested_usage_value(usage, "completion_tokens_details", "reasoning_tokens"),
    }


def get_token_usage_attributes(response: Any) -> dict[str, Any]:
    counts = _extract_token_counts(response)
    key_map = {
        "input_tokens": "gen_ai.usage.input_tokens",
        "output_tokens": "gen_ai.usage.output_tokens",
        "total_tokens": "gen_ai.usage.total_tokens",
        "cached_tokens": "gen_ai.usage.cached_tokens",
        "reasoning_tokens": "gen_ai.usage.reasoning_tokens",
    }
    return {key_map[k]: v for k, v in counts.items() if v is not None}


def get_token_price_per_million(name: str) -> float:
    try:
        return float(os.getenv(name, "0"))
    except ValueError:
        return 0.0


def compute_cost_usd(response: Any) -> float | None:
    counts = _extract_token_counts(response)
    prompt_tokens = counts.get("input_tokens")
    completion_tokens = counts.get("output_tokens")
    cached_tokens = counts.get("cached_tokens")

    input_price = get_token_price_per_million("AZURE_OPENAI_PRICE_INPUT_PER_1M")
    output_price = get_token_price_per_million("AZURE_OPENAI_PRICE_OUTPUT_PER_1M")
    if not (input_price or output_price):
        return None
    if prompt_tokens is None or completion_tokens is None:
        return None

    cached_price = get_token_price_per_million("AZURE_OPENAI_PRICE_CACHED_INPUT_PER_1M") or input_price
    billed_cached = cached_tokens or 0
    uncached_input = prompt_tokens - billed_cached

    cost = (
        (uncached_input / 1_000_000) * input_price
        + (billed_cached / 1_000_000) * cached_price
        + (completion_tokens / 1_000_000) * output_price
    )
    return round(cost, 6)


def get_response_attributes_otel(response: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    response_id = getattr(response, "id", None)
    if response_id:
        attributes["gen_ai.response.id"] = response_id
    response_model = getattr(response, "model", None)
    if response_model:
        attributes["gen_ai.response.model"] = response_model
    choices = getattr(response, "choices", None)
    if choices:
        reasons = [getattr(c, "finish_reason", None) for c in choices]
        reasons = [r for r in reasons if r]
        if reasons:
            attributes["gen_ai.response.finish_reasons"] = reasons
    return attributes


def set_span_attributes(span: trace.Span, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def record_llm_metrics(deployment: str, operation: str, duration_ms: float, token_usage_attributes: dict[str, Any]) -> None:
    common = {"gen_ai.system": "az.ai.openai", "gen_ai.operation.name": operation, "gen_ai.request.model": deployment}
    input_tokens = token_usage_attributes.get("gen_ai.usage.input_tokens")
    if input_tokens is not None:
        gen_ai_token_usage_histogram.record(input_tokens, attributes={**common, "gen_ai.token.type": "input"})
    output_tokens = token_usage_attributes.get("gen_ai.usage.output_tokens")
    if output_tokens is not None:
        gen_ai_token_usage_histogram.record(output_tokens, attributes={**common, "gen_ai.token.type": "output"})
    gen_ai_operation_duration_histogram.record(duration_ms / 1000, attributes=common)


# ============================================================
# GENERIC TRACING WRAPPER
#
# One place all tracing logic lives. Use either form:
#
#   1) Call-site wrapper -- pick a different trace name per call:
#        result = run_traced("document_intelligence_tracker", my_func, arg1, arg2)
#        response = run_traced("chat_tracker", raw_llm_call, client, deployment,
#                               is_llm=True, messages=[...])
#
#   2) Decorator -- tag a function definition once, every call to it
#      is traced the same way:
#        @traced("extraction_tracker")
#        def process_document(...): ...
#
# Both record: input arguments (as input.* attributes), duration_ms,
# success/failure + exception details. When is_llm=True and the
# function's return value looks like an OpenAI response (has a
# `.usage` attribute), it ALSO records gen_ai.* token usage, cost_usd,
# and feeds the metrics histograms -- so you get differently-named
# spans (chat_tracker / document_intelligence_tracker / whatever you
# call it) all built from the same underlying code path.
# ============================================================

_SKIP_ARG_NAMES = {"self", "openai_client", "di_client", "client"}
_MAX_ATTR_LEN = 2000


def _safe_serialize(value: Any) -> str:
    """Turn any function argument into a short, safe-to-store span attribute string."""
    if hasattr(value, "__class__") and value.__class__.__name__ in {"AzureOpenAI", "DocumentIntelligenceClient"}:
        return f"<{value.__class__.__name__}>"
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
    except Exception:
        text = str(value)
    if len(text) > _MAX_ATTR_LEN:
        text = text[:_MAX_ATTR_LEN] + f"...[truncated, {len(text)} chars total]"
    return text


def run_traced(span_name: str, func, *args, is_llm: bool = False, **kwargs) -> Any:
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("function.name", getattr(func, "__name__", str(func)))

        # Capture the function's own arguments as input.* attributes.
        try:
            sig = inspect.signature(func)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            for key, value in bound.arguments.items():
                if key in _SKIP_ARG_NAMES:
                    continue
                span.set_attribute(f"input.{key}", _safe_serialize(value))
        except TypeError:
            pass  # e.g. *args-only functions -- skip payload capture, tracing still proceeds

        started_at = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            span.set_attribute("success", False)
            span.set_attribute("error.type", exc.__class__.__name__)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.error("%s failed: %s: %s", span_name, exc.__class__.__name__, exc)
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        span.set_attribute("duration_ms", duration_ms)
        span.set_attribute("success", True)

        if is_llm and hasattr(result, "usage"):
            deployment = kwargs.get("deployment") or getattr(result, "model", "unknown")
            otel_attrs = get_response_attributes_otel(result)
            otel_attrs.update(get_token_usage_attributes(result))
            set_span_attributes(span, otel_attrs)

            cost_usd = compute_cost_usd(result)
            if cost_usd is not None:
                span.set_attribute("cost_usd", cost_usd)

            record_llm_metrics(deployment, "chat", duration_ms, otel_attrs)

            # Local visibility while testing in a notebook -- App Insights
            # gets the same numbers as span attributes (see above).
            print(
                f"[{span_name}] tokens: input={otel_attrs.get('gen_ai.usage.input_tokens')} "
                f"output={otel_attrs.get('gen_ai.usage.output_tokens')} "
                f"total={otel_attrs.get('gen_ai.usage.total_tokens')} | "
                f"cost_usd={cost_usd} | duration_ms={duration_ms}"
            )

        logger.info("%s succeeded: duration_ms=%s", span_name, duration_ms)
        return result


def traced(span_name: str, is_llm: bool = False):
    """Decorator form of run_traced -- tag a function definition once."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return run_traced(span_name, func, *args, is_llm=is_llm, **kwargs)
        return wrapper
    return decorator


def flush_traces(timeout_millis: int = 10_000) -> None:
    """
    Call this at the end of a notebook cell (or script) so spans/metrics
    are actually exported before you go check Application Insights.
    """
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis)
    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "force_flush"):
        meter_provider.force_flush(timeout_millis)