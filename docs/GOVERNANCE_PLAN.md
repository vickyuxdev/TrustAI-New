# TrustAI Governance — Implementation Plan

**Goal:** an agent built by the internal AI Factory can be **onboarded** into TrustAI, **risk
assessed**, protected by **guardrails & policies**, **evaluated** (red-team), and **deployed behind
the TrustAI AI Gateway** — end to end, with no external governance vendor.

**Status:** implemented 2026-10-27 - phases 0-7 built and tested; AI Factory (Internal) end-to-end verified against live services. Remaining: see "Open items" at the end.
**Ground rules:** local file edits only — no git commit/push. Production-grade code, docstrings,
env-var config, parameterised SQL (SQLAlchemy), secure headers, multi-stage non-root Dockerfiles,
pytest unit tests + one integration test per endpoint, tests green before "done".

---

## 1. Where we start

**TrustAI today (observability):** FastAPI services `ingestion :8001`, `api :8002`, `admin :8003`,
`processor`, `collector`; Next.js dashboard `:3000`; Postgres (metadata) + TimescaleDB (spans) +
Redis; `trustai` Python SDK (`init`, `@agent`, `@llm_call`, `span`). Already has **clients →
projects → agents**, hashed project **API keys** with scopes, Azure AD + RBAC, `audit_logs`, alert
rules. **Missing:** everything governance.

**AI Factory today:** talks to the governance platform only through
`.claude/skills/trustwise-sdk/scripts/tw.py` (13 sub-commands), the `optimize` skill (vendor CLI),
and the generated agent runtime (`agent_runtime.py`: runtime guard + gateway backend). Factory
steps 04–09, `run_evals.py`, `stage_deployment.py`, `deploy_vm.py`, `factscore.py`,
`policy_loop.py`, Studio and factory-runner read the files tw.py writes.

So the job is: **(A)** add a governance plane to TrustAI that offers the same capabilities, and
**(B)** swap the factory's wrapper/runtime/skills to TrustAI while keeping the factory's file
contract (`agent-config.json`, `arc-assessment.json`, `red-team-results.json`, `eval-report.json`,
`deployment-record.json`, evidence) so the downstream scripts keep working.

---

## 2. Target architecture

```
 AI Factory (skills / tai.py / agent runtime)          TrustAI Dashboard (Next.js)
        │  trustai SDK  (trustai.govern.*)  + trustai CLI         │
        ▼                                                         ▼
 ┌──────────────────────────── Governance Service (FastAPI :8004) ─────────────────────────────┐
 │ Registry & Onboarding │ Risk Assessment │ Guardrails & Policies │ Evaluations │ Evidence/Events │
 └───────────┬──────────────────┬──────────────────┬───────────────────┬──────────────────────┘
             │ Postgres (new governance tables)    │ Redis queue        │
             │                                     ▼                    │
             │                          Eval Worker (red-team runner) ──► agent's HTTP endpoint
             │                                     │
             │                          Guardrail Engine (evaluators: PII · prompt-manipulation ·
             │                          toxicity · adherence · tool-permission)
             ▼
 TrustAI AI Gateway (LiteLLM proxy :4000 + TrustAI guardrail plugin)
   OpenAI-compatible /v1/chat/completions · per-agent virtual keys · policy enforced in/out
   · every call traced into existing TrustAI spans (cost + latency for free)
```

New pieces live **inside the existing TrustAI repo** and reuse `shared/` (config, DB sessions,
auth, RBAC, crypto, audit log). Observability and governance meet on the same agent record.

---

## 3. What we build

### 3.1 Governance service — `services/governance/` (FastAPI :8004)

| Module | Endpoints (prefix `/api/v1`) | Notes |
|---|---|---|
| **Registry & onboarding** | `GET/POST /agents`, `GET/PATCH /agents/{id}`, `GET /agents?external_id=`, `POST /agents/{id}/status`, `POST /agents/{id}/test-connection`, `POST /agents/{id}/policies`, `POST/GET /mcp-servers` | Extends existing `agents` table: `external_id` (factory workload id), `version`, `capabilities`, `skills`, `runtime_config` (http base_url, request_template, response_key, timeout), `lifecycle_status` (`registered→onboarded→assessed→evaluated→approved→deployed→retired`), `risk_tier`. |
| **Risk assessment** | `GET /risk/templates`, `POST /assessments`, `PUT /assessments/{id}/answers`, `POST …/validate`, `POST …/submit`, `POST …/classify`, `POST …/decision`, `GET /assessments/{id}` | **TrustAI's own template** (`trustai_build_v1`) built from **EU AI Act risk categories + NIST AI RMF** questions (autonomy, data sensitivity, actions/side-effects, users affected, human oversight). Deterministic, explainable tiering rules → tier 1–4 with reasons. Human decision step (`approved / approved_with_conditions / rejected`) with conditions list, recorded in `audit_logs`. |
| **Guardrails** | `GET/POST/PATCH /guardrails`, `POST /guardrails/{id}/evaluate`, `GET /guardrails/{id}/evaluations` | A guardrail = list of evaluators + thresholds. `evaluate` returns `passed`, per-check `{passed, score}`, `guardrail_eval_id`; every call stored (for evidence). |
| **Policies** | `GET/POST/PATCH /policies`, `GET /policies?search=&tags=`, `POST /policies/recommend` | Policy = guardrails with `phase` (input/output/tool), `severity`, `fail_on_severity_level`. Seed set: *TrustAI Baseline*, *OWASP LLM Top-10 aligned*, *PII-strict*, *Finance actions* — written fresh by us. Recommend = tag match against agent capabilities + risk tier. |
| **Metrics** | `POST /metrics/{pii\|adherence\|toxicity\|prompt_manipulation}` | Stand-alone scoring (used by `optimize`). |
| **Evaluations (red-team)** | `POST /evaluations` (type `red_team`/`classification`), `GET /evaluations/{id}`, `GET /agents/{id}/evaluations` | Async job on Redis. Prompt sources: `custom` (factory dataset), `generate` (LLM generator with attack strategies: injection, jailbreak/role-play, encoding, tool abuse, PII extraction, + benign ratio), `reuse` (previous eval). Results: `trust_score`, `block_rate_pct`, `iterations[{prompt,response,harmful,blocked,error}]`, `per_prompt` FN/FP classification, `per_guardrail`. |
| **Gateway control** | `GET /gateway/models`, `POST /agents/{id}/gateway` (deploy), `DELETE …/gateway` (revoke) | Deploy = create per-agent virtual key in the gateway bound to the agent's policies + allowed model; returns `gateway_url` + one-time key. Gate: latest eval verdict & assessment decision must allow it (server-side, not just in the factory). |
| **Evidence & events** | `GET /agents/{id}/evidence`, `GET /events?target_id=` | One JSON evidence pack (status, tier, decision, guardrail stats, evals, trust score) + policy-violation event feed (replaces the unused `.trustwise/alerts.json`). |

### 3.2 Guardrail engine — `services/governance/app/engine/`

Pluggable evaluator interface (`evaluate(text, context) -> CheckResult`), configured by env vars:

| Evaluator | Default backend | Fallback |
|---|---|---|
| `pii` | Microsoft **Presidio** (local, no data leaves) | regex rules |
| `prompt_manipulation` | **Azure AI Content Safety – Prompt Shields** | LLM-as-judge via gateway |
| `toxicity` | **Azure AI Content Safety** text analysis | LLM-as-judge |
| `adherence` (follows policy text / scope) | LLM-as-judge (rubric prompt, temperature 0) | — |
| `tool_permission` | rule engine (allow/deny lists, approval-required actions from `tools.json`) | — |
| `harmful_compliance` (eval grading only) | LLM-as-judge | — |

Results are cached by hash; circuit breaker + timeouts; judge prompts versioned in repo.

### 3.3 AI Gateway — `services/gateway/`

- **LiteLLM proxy** (reuse RandomTrees' existing `ai-factory-gateway` config: Azure OpenAI +
  OpenRouter open-weight models, no Chinese vendors) in a multi-stage, non-root image.
- **TrustAI guardrail plugin** (LiteLLM custom guardrail hook): pre-call → policy input checks,
  post-call → output checks; block = HTTP 400 with `trustai_guardrail` error body (the factory
  runtime already treats 400/422 "guardrail" as a refusal).
- Per-agent virtual keys created by the governance service; headers `X-TrustAI-Agent-ID`.
- A success/failure callback writes a span to TrustAI ingestion → gateway traffic shows up in the
  existing traces/cost pages automatically.

### 3.4 SDK & CLI — extend `trustai-sdk/`

- `trustai.govern` — typed sync + async client: `agents`, `mcp_servers`, `assessments`,
  `guardrails`, `policies`, `metrics`, `evaluations`, `gateway`, `evidence`. Pydantic models,
  retries, `TrustAIAPIError`, API-key auth (`TRUSTAI_API_KEY`, `TRUSTAI_BASE_URL`).
- `trustai.guard` — runtime helper for agents: `guard.check(phase, text)` with circuit breaker
  (what `agent_runtime.py` needs).
- `trustai` **CLI** (Typer) — `trustai agents|policies|guardrails|evaluations|metrics … --json`,
  same verbs the `optimize` skill uses today.

### 3.5 Dashboard — new pages in `dashboard/`

Agent Registry (lifecycle badge, tier, policies, gateway status) · Risk Assessments (questionnaire,
tier explanation, approve/condition/reject) · Policies & Guardrails (catalog, editor, test box) ·
Evaluations (runs, trust score, per-prompt drill-down) · Gateway (models, deployed agents, revoke) ·
Evidence (export JSON/PDF). Deep links replace the old vendor portal links in Studio.

### 3.6 AI Factory changes (`C:\Users\kishore kumar\Desktop\AI-Factory`)

| Item | Change |
|---|---|
| New skill `trustai-sdk` with `scripts/tai.py` | Same 13 sub-commands as today (`status, setup, guard-test, onboard, onboard-mcp, risk-classify, expose, red-team, red-team-status, gateway-deploy, agent-status, evidence, probe`), same JSON stdout + exit codes, calls TrustAI SDK. |
| Output files | Keep the **same paths and fields** the downstream scripts read; vendor-named ones get TrustAI names (`trustai-onboarding.json`, `trustai-evidence.json`, `.trustai/factory.json`, `agent-config.trustai{}`), with consumers updated: `run_evals.py`, `stage_deployment.py`, `deploy_vm.py`, `factscore.py`, `policy_loop.py`. |
| Agent runtime template | `TrustwiseGuard` → `TrustAIGuard` (SDK `trustai.guard`); `TrustwiseGatewayBackend` → `TrustAIGatewayBackend`; env `TRUSTAI_*`; local PII redaction stays. |
| Skills 04–09, `optimize`, `dataset-generation`, commands `factory:*` | Point at `tai.py` / `trustai` CLI; risk step uses the TrustAI template; Gate 06 unchanged (`eval-report.json.verdict`). |
| Studio / factory-runner / n8n | Health check → TrustAI; deep links → TrustAI dashboard; field names `trustai_commands_run/skipped`. |
| Config | `.env.example`: `TRUSTAI_API_KEY`, `TRUSTAI_BASE_URL`, `TRUSTAI_GATEWAY_URL`. |

---

## 4. Phases & milestones

| # | Phase | Delivers | Done when | Est. |
|---|---|---|---|---|
| 0 | Foundation | `services/governance` skeleton, DB tables + migration (Alembic), API-key scope `govern`, secure headers, Docker, compose entries, test harness (pytest + testcontainers-style Postgres) | service up in compose, health + auth tests green | 2–3 d |
| 1 | Registry & onboarding | agents/MCP endpoints, test-connection, lifecycle, SDK `agents`, dashboard Agent Registry | factory agent JSON → onboarded agent visible in UI | 3–4 d |
| 2 | Guardrails & policies | engine + 5 evaluators, guardrail/policy CRUD, evaluate, seed policies, metrics endpoints, SDK + `trustai.guard`, dashboard page | runtime guard blocks a prompt-injection sample, allows benign; stored eval visible | 5–7 d |
| 3 | Risk assessment | template, answers/validate/submit/classify/decision, SDK, dashboard questionnaire + approval | factory scaffold → answers → tier + human decision | 4–5 d |
| 4 | Evaluations (red-team) | Redis worker, prompt sources (custom/generate/reuse), grading, trust score, classification, SDK, dashboard | 50-prompt run against a factory agent returns results the factory's `run_evals.py` accepts | 5–7 d |
| 5 | AI Gateway | LiteLLM service + guardrail plugin + virtual keys + deploy/revoke + span callback | agent calls gateway; harmful prompt blocked (400), benign answered, trace appears | 4–5 d |
| 6 | Evidence & events | evidence pack, violation events, dashboard Evidence page | `factscore.py` computes trust posture from TrustAI evidence | 2–3 d |
| 7 | AI Factory switch-over | `tai.py`, runtime template, skills/commands, script consumers, Studio/runner, CLI for `optimize` | **E2E:** one workload runs factory steps 04→08 fully on TrustAI, Gate 06 + deploy pass | 5–7 d |

**Total ≈ 6–8 weeks for one engineer with me pairing**, phases 1–3 partly parallel. I can start
Phase 0 immediately after approval and deliver phase by phase, each with tests and a short demo
note.

---

## 5. Out of scope (first release)

Multi-region/HA gateway, model fine-tuning, the vendor's exact score calibration, SOC2 evidence
export, non-HTTP agent runtimes (gRPC/A2A connectors), billing. Added later if needed.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Score quality differs from the old vendor | Calibrate thresholds on the factory's labelled datasets (`custom-redteam-prompts.json`), report FN/FP per guardrail |
| LLM-judge cost/latency | Cache, small judge model via gateway, Presidio/Content Safety first |
| Azure Content Safety not provisioned | Judge fallback works without it; flag in health check |
| Event Hub dependency for ingestion | Governance uses Redis only; gateway spans can post to ingestion directly |
| Factory regressions | Keep file contract; run existing factory script tests + one full workload E2E before switch |

---

## 7. Decisions needed before starting

1. **Factory switch:** replace the old vendor in the AI Factory completely (recommended), or keep
   both behind a `GOVERNANCE_PROVIDER` switch during transition?
2. **Scoring backends:** Azure AI Content Safety + Azure OpenAI judge (recommended — you already use
   Azure), or open-weight judge models via OpenRouter only?
3. **Auth for the factory:** project API key with `govern` scope (recommended) vs Azure AD service
   principal.
4. **Order:** follow phases 0→7 (recommended), or build the gateway first for an earlier demo?

---

## Open items (after the 2026-10-27 build)

1. Run the full stack in Docker (`docker compose up`) - verified so far with local processes + SQLite, not containers.
2. Configure the optional backends (Azure AI Content Safety, LLM judge) and real gateway upstreams (Azure OpenAI /
   OpenRouter) - the end-to-end run used the built-in detectors and a mock model upstream.
3. Run one real factory workload with a real LLM through steps 04-09 (`TRUSTAI_MODE=enabled`).
4. Gate enhancement: also require the tier's required controls (e.g. High-Risk policy for Tier 3) to be attached.
5. Alembic migrations for the governance tables (today: create-on-startup).
