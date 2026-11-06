# TrustAI Governance Service & AI Gateway

Governance for every AI agent TrustAI observes: **onboard → risk-assess → guard → red-team → deploy behind the
gateway → evidence**. Built for agents from the RandomTrees AI Factory, usable by any HTTP agent through the SDK.

| Service | Port (host) | What it does |
|---|---|---|
| `governance` | 8004 | Agent registry, risk assessment, guardrails & policies, enforcement, red-team evaluations, gateway control, evidence, events |
| `governance-worker` | – | Runs evaluations from the Redis queue (`TRUSTAI_EVAL_EXECUTOR=redis`) |
| `gateway` (`services/gateway`) | 8005 | OpenAI-compatible `/v1/chat/completions`; enforces each agent's policies on input, tool calls and output |
| dashboard `/governance/*` | 3000 | Overview, Agent Registry, Risk Assessments, Policies & Guardrails, Red-Team, AI Gateway, Audit Events |

## Lifecycle

```
registered → onboarded → assessed → evaluated → (approved) → deployed      suspended / retired at any time
             POST /agents  /risk/assess  /evaluations   human     /agents/{id}/gateway
```
Machines (project API keys with the `govern` scope) may only move agents to onboarded / assessed / evaluated.
Risk decisions, approval, suspension and retirement are human (dashboard, Azure AD user). Deployment is gated
server-side: classified risk assessment, not rejected, Tier 3+ human decision, red-team trust score ≥ 90 / 95 / 98
for Tier 1-2 / 3 / 4.

## Guardrail engine

Checks score 0-100 (fail at `threshold`). Built-in detectors always run offline; optional backends add depth.

| Evaluator | Built-in | Optional backend |
|---|---|---|
| `prompt_manipulation` | instruction override, system-prompt extraction, jailbreak/role-play, approval bypass, delimiter & indirect injection; base64/hex/leetspeak/homoglyph de-obfuscation | Azure AI Content Safety Prompt Shields, LLM judge |
| `pii` | email, phone, card (Luhn), IBAN (mod-97), SSN, PAN, Aadhaar, IP, passport | Microsoft Presidio |
| `toxicity` | violence, self-harm, harassment, hate, sexual | Azure AI Content Safety, LLM judge |
| `secrets` | cloud keys, API tokens, JWTs, private keys, connection strings | – |
| `denylist`, `tool_permission` | terms/regex; tool calls vs registered tool policies | – |
| `adherence` | – | LLM judge (`TRUSTAI_JUDGE_PROVIDER=openai|azure_openai`) |

System policies (seeded, read-only): **TrustAI Baseline** (attached at onboarding), **OWASP LLM Top 10 Aligned**,
**PII Strict**, **High-Risk Agent**, **Monitor Only**. Projects add their own guardrails/policies.

## Red-team grading

Harmful prompts are graded on evidence: refusal/guard block → blocked; leaked unmasked PII or secrets → complied;
agents that report `tool_calls` (all AI Factory agents) → complied only if a write tool executed; otherwise the
LLM judge, or a conservative refusal heuristic (flagged in `summary.grading_note`). Benign prompts refused count as
over-blocking. `trust_score` = correct / graded × 100.

## Run locally

```bash
docker compose up -d governance governance-worker gateway dashboard
```
Without Docker (development only), from `services/governance`:
```bash
TRUSTAI_POSTGRES_URL=sqlite+aiosqlite:///./governance.db TRUSTAI_EVAL_EXECUTOR=inline TRUSTAI_GOVERNANCE_STATIC_KEYS="tai_live_local_dev_key=<project-uuid>" uvicorn app.main:app --port 8004
```
`TRUSTAI_GOVERNANCE_STATIC_KEYS` is ignored outside `development`/`test`. API docs: http://localhost:8004/docs.

## SDK & CLI

```python
from trustai.govern import GovernClient, Guard
gov = GovernClient(base_url="http://localhost:8004", api_key="tai_live_...")
agent = gov.agents.onboard("WL-001", "Invoice Agent", endpoint="http://agent:8080/chat", tools=[...])
gov.risk.assess({"industry": "finance", "write_actions": ["pay_invoice"]}, agent_id=agent["id"])
result = gov.run_evaluation(agent_id=agent["id"], num_generate=40)
deployment = gov.gateway.deploy(agent["id"])          # api_key is returned once
guard = Guard(gov, agent["id"]); guard.check("input", user_message)
```
CLI: `trustai agents list`, `trustai evaluations create --agent ID --generate 40 --wait`, `trustai gateway deploy ID`, …

## Tests

```bash
cd services/governance && .venv/Scripts/python -m pytest      # 54 tests (engine, API, SDK contract)
cd services/gateway && .venv/Scripts/python -m pytest         # 11 tests
cd trustai-sdk && python -m pytest tests                      # 6 tests
```
