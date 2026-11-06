# TrustAI Python SDK — Developer Integration Guide

> **Enterprise GenAI Observability, Tracing, and Cost Monitoring**  
> Effortlessly instrument AI agents, LLM completions, RAG pipelines, and tool executions with zero latency overhead.

---

## 📑 Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
2. [Installation & Requirements](#2-installation--requirements)
3. [Quickstart (5-Minute Integration)](#3-quickstart-5-minute-integration)
4. [Core Tracing Paradigms](#4-core-tracing-paradigms)
   - [Method 1: Decorators (Recommended)](#method-1-decorators-recommended)
   - [Method 2: Context Manager (`trustai.span`)](#method-2-context-manager-trustaispan)
   - [Method 3: Explicit Span Lifecycle API](#method-3-explicit-span-lifecycle-api)
5. [End-to-End Real World Examples](#5-end-to-end-real-world-examples)
   - [Azure OpenAI / OpenAI Chat Completion](#azure-openai--openai-chat-completion)
   - [Multi-Step AI Agent with Tools](#multi-step-ai-agent-with-tools)
   - [RAG Pipeline (Retrieval + LLM Synthesis)](#rag-pipeline-retrieval--llm-synthesis)
   - [Multi-Turn Chatbot Session](#multi-turn-chatbot-session)
6. [Data Privacy, Security & PII Masking](#6-data-privacy-security--pii-masking)
7. [Error Tracking & Resilience](#7-error-tracking--resilience)
8. [SDK Configuration & Reference](#8-sdk-configuration--reference)
9. [Production Best Practices & Checklist](#9-production-best-practices--checklist)

---

## 1. Overview & Architecture

The **TrustAI SDK** is a lightweight, non-blocking telemetry client designed specifically for LLM and Agentic AI applications. It captures deep observability data including:

- **LLM Metrics**: Input tokens, output tokens, total tokens, cached tokens, reasoning tokens, and USD cost.
- **Trace Waterfalls**: Distributed hierarchy of parent agents, nested tools, knowledge retrieval steps, and completion calls.
- **Payload Capture**: User prompts and assistant responses with automatic client-side PII masking.
- **Latency & Reliability**: Exact execution duration, status codes, error types, and stack traces.
- **Tenant & Client Attribution**: Multi-tenant tagging (`client_id`, `project_id`, `environment`, `user_id`).

### Architecture Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      Your AI Application                    │
│  @trustai.agent │ @trustai.llm_call │ trustai.span(...)    │
└──────────────────────────────┬──────────────────────────────┘
                               │ Non-blocking in-memory buffer
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    TrustAI SDK Flusher                      │
│   • Background daemon thread                                │
│   • Batching & exponential backoff retry                    │
│   • Built-in client-side PII redaction                      │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP POST /v1/traces
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 TrustAI Ingestion Service                   │
│                    (Port 8001)                              │
└──────────────────────────────┬──────────────────────────────┘
                               │ Async Redis / Celery Pipeline
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             TimescaleDB Analytics & PostgreSQL              │
│       • Aggregates, rollups, token tracking, costs          │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 TrustAI Management Dashboard                │
│     Traces Waterfall • Span Inspector • Cost Analytics      │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Installation & Requirements

### Requirements
- **Python**: 3.10+
- **Network**: HTTP access to the TrustAI Ingestion endpoint (default: `http://localhost:8001` or your production cluster URL).

### Install via pip

From the repository root or local directory:
```bash
pip install ./trustai-sdk
```

Or install dependencies directly:
```bash
pip install httpx pydantic
```

---

## 3. Quickstart (5-Minute Integration)

### Step 1: Initialize TrustAI
Call `trustai.init()` once at application startup (e.g., in your `main.py` or entrypoint):

```python
import trustai

trustai.init(
    api_key="tai_live_your_project_key",    # Generated in TrustAI Dashboard
    project_id="your-project-uuid",        # Target project UUID
    environment="production",              # "development" | "staging" | "production"
    ingest_url="http://localhost:8001",    # TrustAI Ingest endpoint
    content_capture_mode="masked",         # "full" | "masked" | "disabled"
    agent_name="support-copilot",          # Default agent identifier
)
```

### Step 2: Instrument Your Functions
Use `@trustai.agent` for top-level agent workflows and `@trustai.llm_call` for model calls:

```python
from openai import AzureOpenAI
import trustai

client = AzureOpenAI(
    azure_endpoint="https://your-resource.openai.azure.com/",
    api_key="your-azure-api-key",
    api_version="2024-08-01-preview"
)

@trustai.llm_call(model="gpt-4o", provider="azure_openai")
def ask_gpt(prompt: str):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
    )
    return response

@trustai.agent(name="qna_agent")
def handle_user_query(query: str):
    response = ask_gpt(query)
    return response.choices[0].message.content

# Run your application
answer = handle_user_query("What is enterprise GenAI observability?")
print(answer)
```

That's it! In the **TrustAI Dashboard (`/traces`)**, you will see:
- A root trace `qna_agent` with status `OK` and total execution time.
- A nested LLM step `ask_gpt` displaying `gpt-4o`, exact prompt tokens, completion tokens, calculated USD cost, and masked prompt/completion text.

---

## 4. Core Tracing Paradigms

TrustAI gives you three flexible ways to instrument code depending on your architecture.

### Method 1: Decorators (Recommended)

Decorators provide zero-boilerplate instrumentation. They work seamlessly on **both synchronous and asynchronous (`async def`) functions**.

#### 1. `@trustai.agent(name=None, tags=None)`
Marks a parent orchestrator function representing an agent execution or session.
- Automatically creates a root trace span.
- Any subsequent LLM calls or tool spans are hierarchically nested under this agent.

```python
@trustai.agent("customer_onboarding_agent", tags={"channel": "web", "tier": "enterprise"})
async def run_onboarding(user_id: str):
    # All inner steps will be linked to this agent run
    ...
```

#### 2. `@trustai.llm_call(name=None, model=None, provider=None, operation="chat")`
Marks an LLM invocation.
- Automatically extracts `input_tokens`, `output_tokens`, `total_tokens`, `cached_tokens`, and `reasoning_tokens` from OpenAI and Azure OpenAI response objects.
- Calculates exact USD cost based on standard model pricing.
- Extracts prompt and completion content according to your `content_capture_mode`.

```python
@trustai.llm_call(model="gpt-4o-mini", provider="azure_openai", operation="chat")
def call_model(messages: list[dict]):
    return client.chat.completions.create(model="gpt-4o-mini", messages=messages)
```

#### 3. `@trustai.trace(name=None, kind="internal", tags=None, capture_args=False)`
Instruments arbitrary internal logic, database queries, preprocessing, or utility functions.
- `kind`: `"internal" | "tool" | "retrieval" | "agent" | "llm"`
- `capture_args=True`: Serializes function arguments into the span attributes.

```python
@trustai.trace(name="validate_input", kind="internal", capture_args=True)
def clean_query(raw_text: str) -> str:
    return raw_text.strip().lower()
```

---

### Method 2: Context Manager (`trustai.span`)

Use `with trustai.span(...)` when you want granular tracing around specific code blocks without wrapping them in separate functions.

```python
import trustai

with trustai.span("vector_search", kind="retrieval") as sp:
    # Set dynamic tags during execution
    sp.tags["collection"] = "kb_enterprise"
    sp.tags["top_k"] = 5
    
    results = vector_index.query(query_embedding, top_k=5)
    
    sp.tags["matches_found"] = len(results)
```

If an exception occurs inside the `with` block:
- The span is automatically marked `success=False`.
- `error_type` and `error_message` are captured.
- The exception is re-raised so normal error handling continues uninterrupted.

---

### Method 3: Explicit Span Lifecycle API

For multi-threaded pipelines, event-driven queues, or complex multi-turn dialogs, you can manually start and finish spans. This gives you full control over `trace_id` and `parent_span_id`.

```python
import trustai

# Start root agent span
agent_span = trustai.init(...).start_span(
    name="agent_workflow",
    kind="agent",
    tags={"session_id": session_id}
)

# Start child span linked to the parent
tool_span = trustai.init(...).start_span(
    name="calculator_tool",
    kind="tool",
    trace_id=agent_span.trace_id,       # Share the same trace ID
    parent_span_id=agent_span.span_id   # Establish parent-child hierarchy
)

try:
    calc_result = run_calculator(expr)
    trustai.init(...).finish_span(tool_span, success=True)
except Exception as e:
    trustai.init(...).finish_span(tool_span, success=False, error=e)
    raise
finally:
    trustai.init(...).finish_span(agent_span, success=True)
```

---

## 5. End-to-End Real World Examples

### Azure OpenAI / OpenAI Chat Completion

```python
import os
import trustai
from openai import AzureOpenAI

# 1. Initialize TrustAI
trustai.init(
    api_key=os.environ.get("TRUSTAI_API_KEY", "tai_live_demo"),
    project_id=os.environ.get("TRUSTAI_PROJECT_ID", "default-project"),
    ingest_url="http://localhost:8001",
    environment="production"
)

# 2. Setup Client
client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version="2024-08-01-preview"
)

# 3. Instrument LLM call
@trustai.llm_call(model="gpt-4o", provider="azure_openai")
def generate_summary(text: str):
    messages = [
        {"role": "system", "content": "Summarize the given text into 3 bullet points."},
        {"role": "user", "content": text}
    ]
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3
    )
    return response

# 4. Invoke
result = generate_summary("OpenTelemetry is a vendor-neutral standard for telemetry data...")
print(result.choices[0].message.content)
```

---

### Multi-Step AI Agent with Tools

```python
import trustai

# 1. Tool Spans (kind="tool")
@trustai.trace(name="currency_converter", kind="tool", capture_args=True)
def convert_currency(amount: float, from_curr: str, to_curr: str) -> float:
    rates = {"USD": 1.0, "EUR": 0.92, "GBP": 0.78, "INR": 83.2}
    usd_amount = amount / rates[from_curr]
    return round(usd_amount * rates[to_curr], 2)

@trustai.trace(name="database_lookup", kind="tool")
def lookup_customer_tier(customer_id: str) -> str:
    return "Platinum"

# 2. LLM Span
@trustai.llm_call(model="gpt-4o", provider="azure_openai")
def synthesize_response(user_prompt: str, context_data: dict):
    return client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a financial advisor assistant."},
            {"role": "user", "content": f"User: {user_prompt}\nContext: {context_data}"}
        ]
    )

# 3. Agent Orchestration
@trustai.agent(name="financial_agent")
def execute_agent(customer_id: str, query: str):
    tier = lookup_customer_tier(customer_id)
    fx_rate = convert_currency(1000.0, "USD", "EUR")
    
    context = {"tier": tier, "conversion_1000_USD_to_EUR": fx_rate}
    reply = synthesize_response(query, context)
    return reply.choices[0].message.content

# Run
execute_agent("cust_9921", "How much is $1,000 in Euros for my account?")
```

In the **TrustAI Waterfall View**, you will see:
```
financial_agent (agent) ─────────────────────────── 1.82s
  ├── lookup_customer_tier (tool) ───── 42ms
  ├── currency_converter (tool) ─────── 18ms
  └── synthesize_response (llm) ────────────────── 1.76s [Tokens: 840 | Cost: $0.0031]
```

---

### RAG Pipeline (Retrieval + LLM Synthesis)

```python
import trustai

@trustai.trace(name="query_expansion", kind="internal")
def expand_query(query: str) -> list[str]:
    return [query, f"{query} best practices", f"{query} architecture"]

@trustai.trace(name="hybrid_retrieval", kind="retrieval")
def retrieve_documents(queries: list[str]) -> list[str]:
    # Simulate vector search
    return [
        "Chunk 1: TrustAI supports automated cost calculation for 40+ LLMs.",
        "Chunk 2: PII masking masks emails, cards, and IPs on the client side."
    ]

@trustai.llm_call(model="gpt-4o-mini", provider="azure_openai")
def answer_rag(query: str, docs: list[str]):
    context = "\n".join(docs)
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": f"Answer using the context:\n{context}"},
            {"role": "user", "content": query}
        ]
    )

@trustai.agent("rag_pipeline")
def run_rag(user_question: str):
    queries = expand_query(user_question)
    docs = retrieve_documents(queries)
    response = answer_rag(user_question, docs)
    return response.choices[0].message.content

run_rag("How does TrustAI handle sensitive user data?")
```

---

### Multi-Turn Chatbot Session

In a conversational bot, ensure all turns correlate to a single persistent user session while isolating each turn's execution:

```python
import uuid
import trustai

def handle_chat_turn(session_id: str, turn_number: int, user_input: str):
    with trustai.span("chat_turn", kind="agent") as turn_span:
        # Tag multi-turn session metadata
        turn_span.tags["session_id"] = session_id
        turn_span.tags["turn"] = turn_number
        turn_span.tags["user_id"] = "user_42"

        # Inner LLM call inherits trace context
        with trustai.span("llm_completion", kind="llm") as llm_span:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": user_input}]
            )
            # Attach token usage directly
            llm_span.usage.input_tokens = response.usage.prompt_tokens
            llm_span.usage.output_tokens = response.usage.completion_tokens
            llm_span.usage.total_tokens = response.usage.total_tokens
            llm_span.model_name = "gpt-4o"
            llm_span.provider = "azure_openai"

        return response.choices[0].message.content
```

---

## 6. Data Privacy, Security & PII Masking

TrustAI is built with privacy-first principles for enterprise deployments (HIPAA, GDPR, SOC2 compliance).

### Content Capture Modes

Configure `content_capture_mode` in `trustai.init(...)`:

| Mode | Prompt / Response Text | Token & Cost Metrics | Use Case |
|---|---|---|---|
| `"masked"` *(Default)* | Client-side PII regex replaced with tokens | Fully preserved | Production environments handling customer data |
| `"full"` | Raw prompt and completion captured | Fully preserved | Internal QA, staging, debugging |
| `"disabled"` | `None` (no text ever leaves memory) | Fully preserved | Strict compliance / zero-retention policies |

### Automatic Client-Side Redaction (`"masked"` mode)
Before spans leave your application process, the SDK redacts:
- **Emails**: `john.doe@example.com` $\rightarrow$ `[EMAIL]`
- **Credit Cards**: `4532-1234-5678-9010` $\rightarrow$ `[CARD]`
- **Phone Numbers**: `+1-555-839-2001` $\rightarrow$ `[PHONE]`
- **IPv4 Addresses**: `192.168.1.50` $\rightarrow$ `[IP]`

### Per-Call Override
You can suppress payload capture for specific sensitive calls (e.g. password resets or SSN lookups):

```python
@trustai.llm_call(model="gpt-4o", capture_messages=False)
def analyze_sensitive_document(doc_text: str):
    ...
```

---

## 7. Error Tracking & Resilience

### Fail-Safe Execution
The SDK operates in a non-blocking background daemon thread. **Telemetry failures will NEVER crash your production application.**
- If the TrustAI ingestion endpoint is unreachable, spans are retried with exponential backoff (`max_retries=3`).
- If the endpoint remains unavailable, spans are dropped gracefully after warnings in your log.

### Capturing Unhandled Exceptions
Any error thrown inside an `@agent`, `@llm_call`, or `with trustai.span` is recorded before re-raising:

```python
@trustai.agent("payment_processor")
def process_payment(amount: float):
    if amount <= 0:
        raise ValueError("Invalid transaction amount")

try:
    process_payment(-50)
except ValueError:
    pass
```

In the TrustAI Dashboard:
- The span is flagged in **Red** with status `Error`.
- `error_type`: `"ValueError"`
- `error_message`: `"Invalid transaction amount"`
- Alerts (Slack/Email/Webhook) configured in TrustAI trigger automatically on error rate spikes.

---

## 8. SDK Configuration & Reference

### `trustai.init(...)` Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api_key` | `str` | *Required* | Project API key from TrustAI dashboard (`tai_live_...`). |
| `project_id` | `str` | *Required* | UUID of the project in TrustAI. |
| `environment` | `str` | `"production"` | Deployment environment (`"production"`, `"staging"`, `"development"`). |
| `ingest_url` | `str` | `"http://localhost:8001"` | TrustAI Ingestion service URL. |
| `content_capture_mode` | `str` | `"masked"` | Payload capture mode: `"masked"`, `"full"`, or `"disabled"`. |
| `agent_name` | `str \| None` | `None` | Default agent label for all spans produced by this process. |
| `batch_size` | `int` | `50` | Maximum number of spans to buffer before triggering an immediate flush. |
| `flush_interval_seconds`| `float` | `5.0` | Maximum interval (in seconds) between automatic buffer flushes. |
| `timeout_seconds` | `float` | `10.0` | HTTP timeout for sending trace batches. |
| `max_retries` | `int` | `3` | Maximum retry attempts for failed batch flushes. |

### Span Object Reference (`Span`)

When using `with trustai.span(...) as sp:` or `client.start_span(...)`, the `Span` object exposes:

| Attribute | Type | Description |
|---|---|---|
| `sp.trace_id` | `str` | Unique 32-character hexadecimal ID for the entire trace tree. |
| `sp.span_id` | `str` | Unique 16-character ID for this specific step. |
| `sp.parent_span_id` | `str \| None` | ID of the parent span in the hierarchy. |
| `sp.span_name` | `str` | Human-readable name of the operation. |
| `sp.span_kind` | `str` | Category: `"agent"`, `"llm"`, `"tool"`, `"retrieval"`, `"internal"`. |
| `sp.model_name` | `str \| None` | Model ID (e.g. `"gpt-4o"`, `"claude-3-5-sonnet"`). |
| `sp.provider` | `str \| None` | Provider name (`"azure_openai"`, `"openai"`, `"aws_bedrock"`). |
| `sp.usage` | `LLMUsage` | Object containing token metrics (`input_tokens`, `output_tokens`, `cost_usd`). |
| `sp.tags` | `dict[str, Any]` | Custom key-value pairs for filtering and analytics in the UI. |
| `sp.attributes` | `dict[str, Any]` | Detailed execution parameters, arguments, or metadata. |

---

## 9. Production Best Practices & Checklist

### ✅ 1. Initialize Once
Always initialize `trustai.init()` at the very top of your application lifecycle (e.g. in FastAPI `lifespan`, Django `AppConfig.ready()`, or CLI entrypoint). Avoid initializing per-request.

### ✅ 2. Graceful Shutdown
In serverless environments (AWS Lambda, Azure Functions) or container shutdown hooks (Kubernetes SIGTERM), ensure all buffered spans are flushed:

```python
import trustai

# At shutdown or container stop:
trustai.shutdown()
```
*(Note: For standard CLI scripts, `atexit` automatically flushes remaining spans).*

### ✅ 3. Tag Meaningful Business Dimensions
Enrich your root agent spans with domain metadata to enable powerful slicing in the dashboard:

```python
@trustai.agent(name="claim_adjuster")
def process_claim(claim_id: str, tenant_id: str):
    with trustai.span("validate") as sp:
        sp.tags["tenant_id"] = tenant_id
        sp.tags["claim_id"] = claim_id
```

### ✅ 4. Set Proper Environment Tags
Always distinguish `"production"`, `"staging"`, and `"development"` so test runs do not skew your production cost analytics and latency percentiles.

---

## Need Help or Have Questions?

- **Dashboard UI**: Access real-time traces and metrics at `http://localhost:3000/traces`
- **Connectors Page**: Manage cloud connectors and API keys at `http://localhost:3000/settings/connectors`
- **Technical Documentation**: See `docs/TRUSTAI_TECHNICAL_DOCUMENTATION.md` for full platform architecture.
