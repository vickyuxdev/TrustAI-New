"""
chatbot.py — TrustAI SDK Demo Chatbot (Azure OpenAI GPT-4o)
=============================================================
A multi-turn CLI chatbot fully instrumented with TrustAI SDK.
Uses Azure OpenAI (GPT-4o) as the LLM backend.

FIX: All child spans (preprocess, retrieval, llm, postprocess) now share
the same trace_id as the parent "chatbot_turn" agent span and have
parent_span_id set correctly. This makes Model / Provider / Tokens / Cost
visible in the TrustAI Dashboard traces view.

What gets tracked in the TrustAI Dashboard:
  ✅ Agents page       → one "chatbot_turn" agent span per message
  ✅ Traces waterfall  → chatbot_turn → preprocess → retrieval → llm → postprocess
  ✅ LLM span          → Model, Provider, Input Tokens, Output Tokens, Cost
  ✅ Content capture   → masked prompts/responses (PII auto-stripped)
  ✅ Error tracking    → failed spans with error_type + error_message
  ✅ Tags              → turn, session_id, user_id, total_tokens on every span

Run:
    cd examples/chatbot-demo
    python chatbot.py
"""

import logging
import os
import sys
import time
import uuid

# ── Allow running from the repo root without pip install ────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "trustai-sdk"))

from openai import AzureOpenAI
from trustai.models import LLMUsage, Span

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("chatbot-demo")

# ══════════════════════════════════════════════════════════════════════════════
# 1. Azure OpenAI Configuration (GPT-4o)
# ══════════════════════════════════════════════════════════════════════════════

def _require_env(name: str) -> str:
    """Returns a required environment variable or exits with a clear message (no secrets in code)."""
    value = os.getenv(name)
    if not value:
        sys.exit(f"Missing required environment variable {name}. Set it in your shell or .env file.")
    return value


AZURE_ENDPOINT    = _require_env("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY     = _require_env("AZURE_OPENAI_API_KEY")
AZURE_API_VERSION = "2025-01-01-preview"
DEPLOYMENT        = "gpt-4o"

# ══════════════════════════════════════════════════════════════════════════════
# 2. TrustAI Configuration
# ══════════════════════════════════════════════════════════════════════════════

TRUSTAI_API_KEY    = _require_env("TRUSTAI_API_KEY")   # chatbot project ingest key (Dashboard → Settings → API Keys)
TRUSTAI_PROJECT_ID = "3a034ff2-7c4a-4839-9da8-0fbd953a9fa3"  # "chatbot" project
TRUSTAI_INGEST_URL = "http://localhost:8001"

# ══════════════════════════════════════════════════════════════════════════════
# 3. Startup Banner
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 62)
print("  TrustAI Chatbot Demo — Azure OpenAI GPT-4o")
print("=" * 62)
print(f"  [TrustAI] Project : {TRUSTAI_PROJECT_ID}")
print(f"  [TrustAI] Ingest  : {TRUSTAI_INGEST_URL}")
print(f"  [LLM]     Model   : {DEPLOYMENT}")
print(f"  [LLM]     Endpoint: {AZURE_ENDPOINT}")
print("=" * 62 + "\n")

# ══════════════════════════════════════════════════════════════════════════════
# 4. Initialise TrustAI SDK
# ══════════════════════════════════════════════════════════════════════════════

import trustai

_sdk = trustai.init(
    api_key=TRUSTAI_API_KEY,
    project_id=TRUSTAI_PROJECT_ID,
    environment="development",
    ingest_url=TRUSTAI_INGEST_URL,
    content_capture_mode="masked",   # full | masked | disabled
    agent_name="demo-chatbot",
    flush_interval_seconds=3.0,
)

logger.info("TrustAI SDK ready — project=%s", TRUSTAI_PROJECT_ID)

# ══════════════════════════════════════════════════════════════════════════════
# 5. Azure OpenAI Client
# ══════════════════════════════════════════════════════════════════════════════

azure_client = AzureOpenAI(
    azure_endpoint=AZURE_ENDPOINT,
    api_key=AZURE_API_KEY,
    api_version=AZURE_API_VERSION,
)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Span helper — creates a child span that shares the parent's trace_id
#
# ROOT CAUSE FIX:
#   The SDK's @trustai.trace / @trustai.llm_call decorators call
#   client.start_span() with no trace_id, so each gets a brand-new trace_id.
#   Every span ends up in a different "trace" — they are orphans in the DB.
#   The Dashboard shows the chatbot_turn entry but can't find the LLM child
#   span (different trace), so Model / Tokens / Cost all show as "—".
#
#   Fix: manually pass trace_id=parent.trace_id and
#        parent_span_id=parent.span_id to every child span.
# ══════════════════════════════════════════════════════════════════════════════

def _child(parent: Span, name: str, kind: str = "internal") -> Span:
    """Create a child span properly linked to a parent span."""
    return _sdk.start_span(
        name=name,
        kind=kind,
        trace_id=parent.trace_id,          # ← same trace as parent
        parent_span_id=parent.span_id,     # ← links to parent in waterfall
    )


# ══════════════════════════════════════════════════════════════════════════════
# 7. Pipeline — all steps are plain functions; spans are managed explicitly
#    inside run_turn() so trace context is always threaded correctly.
# ══════════════════════════════════════════════════════════════════════════════

_KB: dict[str, str] = {
    "trustai":        "TrustAI is an enterprise GenAI observability platform for LLM cost and trace monitoring.",
    "instana":        "IBM Instana is a general-purpose APM tool with GenAI observability via OpenTelemetry.",
    "opentelemetry":  "OpenTelemetry (OTel) is the CNCF standard for distributed tracing, metrics, and logs.",
    "azure":          "Azure OpenAI provides GPT-4o, GPT-4, and other models via the Azure cloud platform.",
    "gpt":            "GPT-4o is OpenAI's latest multimodal model — fast, affordable, and highly capable.",
    "python":         "Python is the dominant language for AI/ML development.",
    "llm":            "Large Language Models (LLMs) are foundation models trained on massive text corpora.",
    "token":          "Tokens are the basic unit LLMs process — roughly 1 token per 4 English characters.",
    "cost":           "LLM API cost = (input_tokens x input_price + output_tokens x output_price) / 1,000,000.",
    "agent":          "An AI agent is an autonomous component that reasons, uses tools, and takes multi-step actions.",
    "rag":            "Retrieval-Augmented Generation (RAG) grounds LLM responses in retrieved document chunks.",
    "observability":  "Observability means understanding a system from its external outputs: logs, metrics, traces.",
}


def _preprocess(raw_text: str) -> str:
    """Validate and clean user input."""
    text = raw_text.strip()
    if not text:
        raise ValueError("Empty user input — nothing to process.")
    if len(text) > 2000:
        logger.warning("Input truncated: %d -> 2000 chars", len(text))
        text = text[:2000] + " ...[truncated]"
    time.sleep(0.02)
    return text


def _retrieve(query: str) -> str:
    """Keyword knowledge-base lookup (simulates a RAG retrieval step)."""
    time.sleep(0.05)
    q = query.lower()
    hits = [v for k, v in _KB.items() if k in q]
    if hits:
        logger.info("Knowledge retrieval — %d hit(s)", len(hits))
    return "\n".join(f"- {h}" for h in hits[:3])


def _postprocess(raw_content: str) -> str:
    """Lightly validate and format the LLM output."""
    if not raw_content or not raw_content.strip():
        return "The model returned an empty response. Please try again."
    time.sleep(0.01)
    return raw_content.strip()


# ══════════════════════════════════════════════════════════════════════════════
# 8. Agent Orchestrator — one turn = one "chatbot_turn" root span
#    All child spans explicitly receive the same trace_id + parent_span_id.
# ══════════════════════════════════════════════════════════════════════════════

def run_turn(
    user_message: str,
    history: list[dict],
    session_id: str,
    turn: int,
    user_id: str,
) -> str:
    """Execute one full chatbot turn. All spans share a single trace_id."""

    # ── ROOT span (agent) ─────────────────────────────────────────────────────
    agent_span = _sdk.start_span(
        name="chatbot_turn",
        kind="agent",
        tags={
            "session_id": session_id,
            "turn":       turn,
            "user_id":    user_id,
            "model":      DEPLOYMENT,
            "provider":   "azure_openai",
        },
    )
    # All child spans use this trace_id + this span_id as parent
    TRACE_ID  = agent_span.trace_id
    PARENT_ID = agent_span.span_id

    try:
        # ── STEP 1: Preprocess ────────────────────────────────────────────────
        pre_span = _sdk.start_span("preprocess_user_input", kind="internal",
                                   trace_id=TRACE_ID, parent_span_id=PARENT_ID)
        try:
            cleaned = _preprocess(raw_text=user_message)
            agent_span.tags["input_length_chars"] = len(cleaned)
            _sdk.finish_span(pre_span, success=True)
        except Exception as exc:
            _sdk.finish_span(pre_span, success=False, error=exc)
            _sdk.finish_span(agent_span, success=False, error=exc)
            raise

        # ── STEP 2: Knowledge retrieval ───────────────────────────────────────
        ret_span = _sdk.start_span("knowledge_retrieval", kind="retrieval",
                                   trace_id=TRACE_ID, parent_span_id=PARENT_ID)
        try:
            context = _retrieve(query=cleaned)
            agent_span.tags["context_retrieved"] = bool(context)
            _sdk.finish_span(ret_span, success=True)
        except Exception as exc:
            _sdk.finish_span(ret_span, success=False, error=exc)
            _sdk.finish_span(agent_span, success=False, error=exc)
            raise

        # ── STEP 3: Build messages ────────────────────────────────────────────
        system_msg = (
            "You are a helpful AI assistant powered by Azure OpenAI GPT-4o, "
            "embedded in the TrustAI observability platform demo. "
            "Answer clearly and concisely. If you don't know something, say so."
        )
        messages: list[dict] = [{"role": "system", "content": system_msg}]
        if context:
            messages.append({"role": "system",
                              "content": f"Relevant background:\n{context}"})
        messages.extend(history[-12:])
        messages.append({"role": "user", "content": cleaned})

        # ── STEP 4: LLM call ──────────────────────────────────────────────────
        # This is the key span: it needs to carry model, provider, tokens, cost.
        llm_span = _sdk.start_span("chat_completion", kind="llm",
                                   trace_id=TRACE_ID, parent_span_id=PARENT_ID)
        try:
            import json as _json
            response = azure_client.chat.completions.create(
                model=DEPLOYMENT,
                messages=messages,
                temperature=0.7,
                max_tokens=512,
            )

            # ── Populate all LLM fields on the span ──────────────────────────
            llm_span.provider   = "azure_openai"
            llm_span.model_name = DEPLOYMENT
            llm_span.operation  = "chat"

            if response.usage:
                u = response.usage
                llm_span.usage = LLMUsage(
                    input_tokens=getattr(u, "prompt_tokens", None),
                    output_tokens=getattr(u, "completion_tokens", None),
                    total_tokens=getattr(u, "total_tokens", None),
                    cached_tokens=getattr(
                        getattr(u, "prompt_tokens_details", None),
                        "cached_tokens", None
                    ),
                )

            if response.choices:
                llm_span.finish_reason = getattr(response.choices[0], "finish_reason", None)

            # Input / output content (SDK masks PII per content_capture_mode)
            input_text  = _json.dumps(messages, default=str)
            output_text = (response.choices[0].message.content
                           if response.choices else None)

            _sdk.finish_span(llm_span, success=True,
                             input_content=input_text,
                             output_content=output_text)
        except Exception as exc:
            _sdk.finish_span(llm_span, success=False, error=exc)
            _sdk.finish_span(agent_span, success=False, error=exc)
            raise

        # ── STEP 5: Extract reply ─────────────────────────────────────────────
        raw_reply = response.choices[0].message.content if response.choices else ""

        # ── STEP 6: Postprocess ───────────────────────────────────────────────
        post_span = _sdk.start_span("postprocess_response", kind="internal",
                                    trace_id=TRACE_ID, parent_span_id=PARENT_ID)
        try:
            final_reply = _postprocess(raw_content=raw_reply)
            _sdk.finish_span(post_span, success=True)
        except Exception as exc:
            _sdk.finish_span(post_span, success=False, error=exc)
            _sdk.finish_span(agent_span, success=False, error=exc)
            raise

        # ── Bubble token totals up to the agent span ──────────────────────────
        if response.usage:
            agent_span.tags["total_tokens"]  = getattr(response.usage, "total_tokens", 0)
            agent_span.tags["input_tokens"]  = getattr(response.usage, "prompt_tokens", 0)
            agent_span.tags["output_tokens"] = getattr(response.usage, "completion_tokens", 0)

        _sdk.finish_span(agent_span, success=True)
        return final_reply

    except Exception as exc:
        # Ensure root span is always finished even on unexpected errors
        try:
            _sdk.finish_span(agent_span, success=False, error=exc)
        except Exception:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# 9. Main — CLI conversation loop
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    session_id = uuid.uuid4().hex[:12]
    user_id    = f"user-{session_id[:6]}"
    history: list[dict] = []
    turn = 0

    print("  Every message is fully traced to TrustAI:")
    print("  -> Dashboard -> Agents  : agent spans per turn")
    print("  -> Dashboard -> Traces  : full linked waterfall (preprocess -> retrieval -> llm -> postprocess)")
    print("  -> Dashboard -> Traces  : Model / Provider / Tokens / Cost on each LLM span")
    print()
    print("  Commands: 'quit'/'exit'  |  'flush' force-flush  |  'stats' session info")
    print("=" * 62 + "\n")

    session_turns = 0

    while True:
        try:
            raw = input(f"[Turn {turn + 1}] You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Exiting — flushing remaining spans...")
            break

        if not raw:
            continue

        if raw.lower() in {"quit", "exit"}:
            print("  Flushing remaining spans and shutting down...")
            break

        if raw.lower() == "flush":
            trustai.flush()
            print("  Spans force-flushed to TrustAI ingestion service.\n")
            continue

        if raw.lower() == "stats":
            print(f"\n  Session {session_id} | Turns: {session_turns}\n")
            continue

        turn += 1
        t0 = time.perf_counter()

        try:
            reply = run_turn(
                user_message=raw,
                history=history,
                session_id=session_id,
                turn=turn,
                user_id=user_id,
            )
        except ValueError as exc:
            logger.warning("Turn %d skipped: %s", turn, exc)
            print(f"  {exc}\n")
            turn -= 1
            continue
        except Exception as exc:
            logger.error("Turn %d failed — %s: %s", turn, type(exc).__name__, exc)
            print(f"  Error: {exc}\n")
            turn -= 1
            continue

        elapsed = round(time.perf_counter() - t0, 2)
        session_turns += 1

        print(f"\n  Assistant [{DEPLOYMENT}]: {reply}")
        print(f"\n  [{elapsed}s | GPT-4o via Azure | spans -> TrustAI @ localhost:3000]\n")

        history.append({"role": "user",      "content": raw})
        history.append({"role": "assistant", "content": reply})

    trustai.shutdown()
    print(f"\n  Done. {session_turns} turn(s) traced to TrustAI.")
    print("  -> Open http://localhost:3000 -> Agents to see your data.\n")


if __name__ == "__main__":
    main()
