"""
trustai/decorators.py
Developer-facing decorator API — the primary integration surface for TrustAI.

Usage:
    import trustai

    trustai.init(api_key="tai_live_xxx", project_id="...", environment="prod")

    @trustai.agent("document_processor")
    def process_document(file_path: str):
        ...

    @trustai.llm_call(model="gpt-4o", provider="azure_openai")
    def run_extraction(client, messages: list) -> Any:
        return client.chat.completions.create(model="gpt-4o", messages=messages)

    # For async functions — works identically:
    @trustai.llm_call(model="gpt-4o")
    async def run_async_llm(client, messages):
        return await client.chat.completions.create(model="gpt-4o", messages=messages)

    # Explicit span with custom context manager:
    with trustai.span("my_step") as sp:
        result = do_something()
        sp.tags["doc_type"] = "invoice"
"""
import asyncio
import functools
import inspect
import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable

from trustai.models import LLMUsage, Span

logger = logging.getLogger("trustai.sdk")

# Global client — set by trustai.init()
_client: Any = None  # TrustAIClient | None


def _get_client():
    if _client is None:
        raise RuntimeError(
            "TrustAI SDK not initialised. Call trustai.init(...) before using decorators."
        )
    return _client


# ─────────────────────────────────────────────────────────────────
# @trustai.trace — generic span decorator
# ─────────────────────────────────────────────────────────────────

def trace(
    name: str | None = None,
    kind: str = "internal",
    tags: dict[str, Any] | None = None,
    capture_args: bool = False,
) -> Callable:
    """
    General-purpose span decorator. Works on sync and async functions.

    Args:
        name: Span name. Defaults to the decorated function's name.
        kind: Span kind ("internal", "tool", "retrieval", etc.)
        tags: Static tags to attach to every span.
        capture_args: If True, serialises function arguments as span attributes.
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__
        is_async = inspect.iscoroutinefunction(func)

        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                client = _get_client()
                sp = client.start_span(span_name, kind=kind, tags=tags or {})
                if capture_args:
                    sp.attributes.update(_capture_args(func, args, kwargs))
                try:
                    result = await func(*args, **kwargs)
                    client.finish_span(sp, success=True)
                    return result
                except Exception as exc:
                    client.finish_span(sp, success=False, error=exc)
                    raise
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                client = _get_client()
                sp = client.start_span(span_name, kind=kind, tags=tags or {})
                if capture_args:
                    sp.attributes.update(_capture_args(func, args, kwargs))
                try:
                    result = func(*args, **kwargs)
                    client.finish_span(sp, success=True)
                    return result
                except Exception as exc:
                    client.finish_span(sp, success=False, error=exc)
                    raise
            return sync_wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────
# @trustai.agent — marks an agent execution (parent span)
# ─────────────────────────────────────────────────────────────────

def agent(
    name: str | None = None,
    tags: dict[str, Any] | None = None,
) -> Callable:
    """
    Marks an agent function. Creates a root span for the agent execution.
    All LLM calls made inside the function are automatically nested under this span.
    """
    def decorator(func: Callable) -> Callable:
        return trace(name=name or func.__name__, kind="agent", tags=tags)(func)
    return decorator


# ─────────────────────────────────────────────────────────────────
# @trustai.llm_call — LLM span with automatic token + cost tracking
# ─────────────────────────────────────────────────────────────────

def llm_call(
    name: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    operation: str = "chat",
    capture_messages: bool | None = None,  # None = inherit from project config
) -> Callable:
    """
    Decorator for functions that make an LLM API call.
    Automatically extracts token usage, cost, finish reason, and model from
    the response if it follows the OpenAI SDK response shape.

    Args:
        name: Span name. Defaults to the function name.
        model: Model name (e.g., "gpt-4o"). If None, extracted from response.
        provider: Provider name (e.g., "azure_openai", "openai").
        operation: Operation type ("chat", "embedding", "completion").
        capture_messages: Override content capture for this specific call.
                          None inherits from the project's content_capture_mode.
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__
        is_async = inspect.iscoroutinefunction(func)

        def _process_response(sp: Span, result: Any) -> None:
            """Extract metadata from an OpenAI-shaped response and attach to span."""
            sp.provider = provider or _infer_provider(result)
            sp.model_name = model or getattr(result, "model", None)
            sp.operation = operation

            # Handle (result, usage) tuple or single object
            target_obj = result
            if isinstance(result, tuple) and len(result) >= 2:
                for item in result:
                    if hasattr(item, "prompt_tokens") or hasattr(item, "total_tokens"):
                        usage_obj = item
                        break
                    if hasattr(item, "usage"):
                        target_obj = item
                        break

            usage_obj = getattr(target_obj, "usage", None) if not hasattr(target_obj, "prompt_tokens") else target_obj
            if usage_obj:
                sp.usage = LLMUsage(
                    input_tokens=_safe_int(getattr(usage_obj, "prompt_tokens", None) or getattr(usage_obj, "input_tokens", None)),
                    output_tokens=_safe_int(getattr(usage_obj, "completion_tokens", None) or getattr(usage_obj, "output_tokens", None)),
                    total_tokens=_safe_int(getattr(usage_obj, "total_tokens", None)),
                    cached_tokens=_safe_int(
                        getattr(getattr(usage_obj, "prompt_tokens_details", None), "cached_tokens", None)
                    ),
                    reasoning_tokens=_safe_int(
                        getattr(getattr(usage_obj, "completion_tokens_details", None), "reasoning_tokens", None)
                    ),
                )
                sp.usage.cost_usd = _compute_cost(sp.usage)

            choices = getattr(target_obj, "choices", None)
            if choices and len(choices) > 0:
                sp.finish_reason = getattr(choices[0], "finish_reason", None)

        def _get_content(func_name: str, args, kwargs, result: Any) -> tuple[str | None, str | None]:
            """Extract input messages and output text for content capture."""
            messages = kwargs.get("messages") or (args[1] if len(args) > 1 else None)
            input_text: str | None = None
            if messages:
                try:
                    input_text = json.dumps(messages, default=str)
                except Exception:
                    input_text = str(messages)

            output_text: str | None = None
            choices = getattr(result, "choices", None)
            if choices:
                first_choice = choices[0]
                msg = getattr(first_choice, "message", None)
                if msg:
                    output_text = getattr(msg, "content", None)
            return input_text, output_text

        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                client = _get_client()
                sp = client.start_span(span_name, kind="llm")
                try:
                    result = await func(*args, **kwargs)
                    _process_response(sp, result)
                    inp, out = _get_content(func.__name__, args, kwargs, result)
                    client.finish_span(sp, success=True, input_content=inp, output_content=out)
                    return result
                except Exception as exc:
                    client.finish_span(sp, success=False, error=exc)
                    raise
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                client = _get_client()
                sp = client.start_span(span_name, kind="llm")
                try:
                    result = func(*args, **kwargs)
                    _process_response(sp, result)
                    inp, out = _get_content(func.__name__, args, kwargs, result)
                    client.finish_span(sp, success=True, input_content=inp, output_content=out)
                    return result
                except Exception as exc:
                    client.finish_span(sp, success=False, error=exc)
                    raise
            return sync_wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────
# Context manager — trustai.span(...)
# ─────────────────────────────────────────────────────────────────

@contextmanager
def span(
    name: str,
    kind: str = "internal",
    tags: dict[str, Any] | None = None,
):
    """
    Context manager for manual span creation.

    Example:
        with trustai.span("embedding_lookup", kind="retrieval") as sp:
            results = vector_db.search(query)
            sp.tags["result_count"] = len(results)
    """
    client = _get_client()
    sp = client.start_span(name, kind=kind, tags=tags or {})
    try:
        yield sp
        client.finish_span(sp, success=True)
    except Exception as exc:
        client.finish_span(sp, success=False, error=exc)
        raise


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

_SKIP_ARG_NAMES = {"self", "cls", "client", "openai_client", "di_client"}
_MAX_ATTR_LEN = 2000


def _capture_args(func: Callable, args, kwargs) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        result = {}
        for key, value in bound.arguments.items():
            if key in _SKIP_ARG_NAMES:
                continue
            try:
                text = value if isinstance(value, str) else json.dumps(value, default=str)
                if len(text) > _MAX_ATTR_LEN:
                    text = text[:_MAX_ATTR_LEN] + "...[truncated]"
                result[f"input.{key}"] = text
            except Exception:
                result[f"input.{key}"] = str(value)[:_MAX_ATTR_LEN]
        return result
    except Exception:
        return {}


def _infer_provider(response: Any) -> str:
    """Infer provider from response object class hierarchy."""
    module = getattr(type(response), "__module__", "")
    if "azure" in module.lower():
        return "azure_openai"
    if "openai" in module.lower():
        return "openai"
    if "anthropic" in module.lower():
        return "anthropic"
    return "unknown"


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


import os

def _compute_cost(usage: LLMUsage) -> float | None:
    """Backward-compatible cost computation using env vars (same as tracing_utils.py)."""
    try:
        input_price = float(os.getenv("AZURE_OPENAI_PRICE_INPUT_PER_1M", "0") or "0")
        output_price = float(os.getenv("AZURE_OPENAI_PRICE_OUTPUT_PER_1M", "0") or "0")
        if not (input_price or output_price):
            return None
        if usage.input_tokens is None or usage.output_tokens is None:
            return None
        cached = usage.cached_tokens or 0
        cached_price = float(os.getenv("AZURE_OPENAI_PRICE_CACHED_INPUT_PER_1M", "0") or input_price)
        cost = (
            ((usage.input_tokens - cached) / 1_000_000) * input_price
            + (cached / 1_000_000) * cached_price
            + (usage.output_tokens / 1_000_000) * output_price
        )
        return round(cost, 6)
    except Exception:
        return None
