# TrustAI Chatbot Demo

A minimal multi-turn CLI chatbot that demonstrates **full TrustAI SDK instrumentation** — every span type, every metric, visible in the Dashboard.

## What Gets Tracked

| Dashboard Location | What You'll See |
|---|---|
| **Agents page** | One `chatbot_turn` agent span per message, with `session_id`, `turn`, `user_id`, `total_tokens` tags |
| **Traces / Waterfall** | Full span tree: `chatbot_turn` → `preprocess_user_input` → `knowledge_retrieval` → `chat_completion` → `postprocess_response` |
| **Cost dashboard** | Per-call `cost_usd` (computed from token counts × model pricing) |
| **Span detail** | `input_content` + `output_content` (masked or full, per your capture mode) |

## Span Architecture

```
chatbot_turn  (kind=agent)
├── preprocess_user_input   (kind=internal)   — input validation + sanitisation
├── knowledge_retrieval     (kind=retrieval)  — simulated RAG / keyword KB lookup
├── chat_completion         (kind=llm)        — LLM API call with token + cost tracking
└── postprocess_response    (kind=internal)   — output formatting
```

## Setup & Run

### 1. Start TrustAI (if not already running)
```bash
cd C:\Users\kishore kumar\Desktop\TrustAI
docker compose up -d
# Dashboard: http://localhost:3000
# Ingestion: http://localhost:8001
```

### 2. Get your API key and Project ID
1. Open **http://localhost:3000**
2. Go to **Settings → API Keys** → generate a new key (`tai_live_...`)
3. Go to **Projects** → copy your project UUID

### 3. Install dependencies
```bash
cd examples/chatbot-demo
pip install -e ../../trustai-sdk    # install TrustAI SDK from local source
pip install -r requirements.txt     # python-dotenv + httpx
```

### 4. Configure .env
```bash
cp .env.example .env
# Edit .env — set TRUSTAI_API_KEY and TRUSTAI_PROJECT_ID at minimum
```

### 5. Run
```bash
python chatbot.py
```

## Chat Commands

| Input | Action |
|---|---|
| Any text | Sends a message — one full traced turn |
| `flush` | Force-flushes all buffered spans immediately |
| `stats` | Shows session turn count |
| `quit` / `exit` | Flush + graceful shutdown |

## Simulated vs Real LLM

| Mode | How to enable | What changes |
|---|---|---|
| **Simulated** (default) | `USE_REAL_OPENAI=false` | Fake responses with realistic token counts — no API key needed |
| **Real OpenAI** | `USE_REAL_OPENAI=true` + `OPENAI_API_KEY=sk-...` | Actual GPT responses — real token usage and cost |

In both modes the TrustAI span structure, tags, and metrics are **identical**.

## Content Capture Modes

Set `TRUSTAI_CAPTURE_MODE` in `.env`:

| Mode | What TrustAI stores |
|---|---|
| `full` | Complete prompt text + full LLM response |
| `masked` | Prompt/response with PII replaced: `[EMAIL]`, `[PHONE]`, `[CARD]`, `[IP]` |
| `disabled` | No content stored — only token counts, cost, timing |

## Understanding the Dashboard

After a few chat messages, open **http://localhost:3000** and:

1. **Agents tab** — see each `chatbot_turn` with its tags and duration
2. **Click any agent** — expand the span waterfall to see all child spans
3. **Cost tab** — see `cost_usd` per LLM call (requires pricing env vars)
4. **Traces tab** — raw span list with filtering by model, provider, success/fail
