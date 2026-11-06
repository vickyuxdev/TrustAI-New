# TrustAI — Explained Simply

_What was built, how it works, how to use it, and what you get out of it._
_Last updated: 2026-10-28_

---

## 1. The idea in one picture

The **AI Factory** builds AI agents. **TrustAI** makes sure every agent is **safe, checked and controlled**
before and after it goes live — like a security + quality department for AI agents.

```text
   +----------------+   1. register it    +-----------------------+
   |  AI FACTORY    | ------------------> |       TRUSTAI         |
   | (builds the    |                     | (checks and controls) |
   |    agent)      |                     |                       |
   +----------------+                     |  2. rate the risk     |
                                          |  3. attack-test it    |
            +-----------------+           |  4. approve + give    |
            |  A PERSON       | --------> |     a gateway key     |
            | approves risky  | approves  +-----------------------+
            | (Tier 3+) agents|                |              |
            +-----------------+       attack-  |              | key
                                       tests   v              v
                                  +-------------+  5. every  +-------------+         +-------------+
                                  |  THE AGENT  | ---------> | AI GATEWAY  | ------> |  AI MODEL   |
                                  |             |  AI call   | (secure     |  safe   | (GPT/Claude)|
                                  +-------------+            |   door)     |  calls  +-------------+
                                                             +-------------+
```

**Before:** TrustAI could only *watch* agents (traces and cost).
**Now:** TrustAI can also *govern* them — register, rate, test, approve, protect and audit.

---

## 2. What TrustAI does now — in plain words

| Feature | What it means (simple) | Real-life comparison |
|---|---|---|
| **Onboarding** | The agent is registered in TrustAI with its tools and rules | An employee getting an ID card |
| **Risk assessment** | 20 questions → the agent gets a risk level, **Tier 1 (low) to Tier 4 (critical)** | A credit rating |
| **Guardrails** | Automatic filters that catch attacks, personal data, toxic text, leaked passwords, forbidden tool use | Airport security scanner |
| **Policies** | A group of guardrails + where to apply them (input, output, tools) + how strict | The security rules of a building |
| **Red-team test** | TrustAI attacks the agent with tricky prompts and scores it **0–100** | A fire drill / penetration test |
| **Human approval** | A person must approve risky (Tier 3+) agents — machines can't approve themselves | A manager's signature |
| **AI Gateway** | A single secure door every AI call passes through; bad calls are blocked | A toll gate with a guard |
| **Runtime guard** | Inside the agent: every message is checked by TrustAI before the AI sees it | A bouncer at the door |
| **Evidence** | One report with everything that happened to the agent | An audit file |
| **Optimisation** | Looks at what the agent failed and recommends stronger policies | A coach's feedback |
| **Dashboard** | 9 screens to see and manage all of the above (RandomTrees theme) | A control room |

---

## 3. The life of an agent (the lifecycle)

Every agent moves through these stages. TrustAI records **who** moved it, **when** and **why**.

```text
   [ start ]
       |
       |  factory registers the agent
       v
   +-----------+   risk assessment    +-----------+   red-team test    +-----------+
   | ONBOARDED | -------------------> | ASSESSED  | -----------------> | EVALUATED |
   +-----------+     (Tier 1-4)       +-----------+   (trust score)    +-----------+
                                                                         |     ^
                                       Tier 3+: a PERSON must approve    |     | key revoked
                                       gate passed + key issued          v     | (kill switch)
                                                                       +-----------+
                                                                       | DEPLOYED  |
                                                                       +-----------+

   At any time a PERSON can:   SUSPEND  -->  RETIRE
```

**Rules that keep it safe**
- The factory (a machine) can only move an agent to *onboarded / assessed / evaluated*.
- *Approve, suspend, retire* = **people only**.
- *Deployed* happens **only** through the gateway gate (never by hand).

---

## 4. How each part works

### 4.1 Risk assessment — "how dangerous could this agent be?"

```text
   FACTS from the factory            20 QUESTIONS                 POINTS per answer
   (industry, write actions,  --->   (EU AI Act +         --->    e.g. finance          +15
    personal data, autonomy...)       NIST AI RMF)                     approval gates     -8
                                                                          |
                                                                          v
                                                                    TOTAL SCORE
                                                                          |
            +--------------------+--------------------+--------------------+
            |                    |                    |                    |
         under 20             20 - 39              40 - 74          75+ or a hard rule
            |                    |                    |                    |
     TIER 1 - Minimal     TIER 2 - Limited     TIER 3 - High        TIER 4 - Critical
                                                      |                    |
                                                      +---------+----------+
                                                                |
                                                     A PERSON must decide
```

- Answers the factory can't know get a **cautious default**, clearly marked *"assumed — please confirm"*.
- Every point is shown, so the tier is **explainable**, not a black box.
- Hard rules override the score (e.g. a prohibited practice is always Tier 4).

### 4.2 Guardrails & policies — "the filters"

```text
   POLICY: "TrustAI Baseline"
   |
   +-- Rule: on INPUT  (severity 4) --> GUARDRAIL "Input Shield"
   |                                        - prompt injection / jailbreak
   |                                        - toxicity
   |
   +-- Rule: on OUTPUT (severity 4) --> GUARDRAIL "Output Safety"
   |                                        - toxicity
   |                                        - leaked secrets (API keys, passwords)
   |
   +-- Rule: on TOOLS  (severity 4) --> GUARDRAIL "Tool Guard"
                                            - forbidden tools
                                            - instructions hidden inside data
```

Each check gives a **risk score 0–100**. If the score crosses the threshold → the check fails → the policy
**blocks** the message (if the rule is strict enough) and logs a **violation event**.

**Built-in checks (work offline, no AI needed):**
prompt injection & jailbreak (even hidden in base64/leetspeak), personal data (emails, cards, IBAN, Aadhaar, PAN…),
toxicity, secrets (API keys, passwords), deny-lists, tool permissions.
**Optional add-ons:** Azure AI Content Safety, an AI "judge" model, Microsoft Presidio.

**Ready-made policies:** TrustAI Baseline · OWASP LLM Top 10 · PII Strict · High-Risk Agent · Monitor Only.

### 4.3 Red-team test — "attack it before the bad guys do"

```text
     TRUSTAI                                            THE AGENT (running)
        |                                                      |
        |  build prompts: your test set                        |
        |  + generated attacks + normal questions              |
        |                                                      |
        |  ---------- send prompt (4 at a time) ------------>  |
        |  <--------- answer + tools it really used ---------  |
        |                                                      |
        |  grade it:  blocked?  leaked data?  ran a payment?   |
        |      ... repeat for every prompt ...                 |
        |                                                      |
        |  TRUST SCORE = correct answers / all answers x 100   |
```

- **Attack prompts** must be blocked. **Normal questions** must be answered (otherwise it's "over-blocking").
- Grading is **evidence-based**: for factory agents TrustAI looks at what the agent *actually did*
  (did a payment tool run? did personal data leak?), not just at the wording of the answer.

### 4.4 The gate + AI Gateway — "only approved agents get a key"

```text
   DEPLOY REQUEST
        |
        v
   [1] Risk assessed? ------------------------------ no --> BLOCKED (reason shown)
        | yes
        v
   [2] Not rejected? ------------------------------- no --> BLOCKED
        | yes
        v
   [3] Tier 3+ : approved by a person? ------------- no --> BLOCKED
        | yes
        v
   [4] Trust score high enough?  -------------------- no --> BLOCKED
       (Tier 1-2: 90 | Tier 3: 95 | Tier 4: 98)
        | yes
        v
   ONE-TIME GATEWAY KEY issued   +   agent status = DEPLOYED
```

After deployment, the agent talks to its AI model **through the gateway**:

```text
   +---------+  "Bearer tai_gw_..."  +------------------+
   |  AGENT  | --------------------> |  TRUSTAI GATEWAY |
   +---------+                       +------------------+
        ^                                     |
        |                          1. check the INPUT against the agent policies
        |                                     |
        |                    bad -------------+------------- ok
        |                     |                              |
        |              400 BLOCKED                           v
        |          (agent answers with                +-------------+
        |              a refusal)                     |  AI MODEL   |
        |                                             +-------------+
        |                                                    |
        |                          2. check the OUTPUT and any tool calls
        |                                                    |
        +---------------------- ok --------------------------+   (bad -> 400 BLOCKED)
```

The key is shown **once**, stored only as a fingerprint (hash), and can be **revoked instantly** (kill switch).

---

## 5. How it's all organised (structure)

### 5.1 The big blocks

```text
   DESKTOP\INTERNAL\AI-FACTORY                         DESKTOP\TRUSTAI
   +----------------------------+                      +-------------------------------------+
   | trustai.py                 |                      |  GOVERNANCE SERVICE  :8004          |
   |  (the 9 factory commands)  |                      |  "the brain"                        |
   |        |                   |                      |    registry, risk, guardrails,      |
   |        v                   |   onboard, risk,     |    policies, red-team, gate,        |
   | trustai_client.py ---------+--------------------->|    evidence, events                 |
   |                            |   red-team, deploy   |            |                        |
   | agent_runtime.py           |                      |        [ DATABASE ]                 |
   |  (inside every agent)      |                      |            ^                        |
   |   - guard -----------------+--- check every ----->|            |                        |
   |   - gateway backend -------+--- AI calls -------> |  AI GATEWAY  :8005 (secure door)    |
   +----------------------------+                      |                                     |
                                                       |  DASHBOARD   :3001 (control room)   |
                                                       |  SDK + CLI   (for developers)       |
                                                       +-------------------------------------+
```

### 5.2 Folders

```
Desktop\TrustAI
├── services\
│   ├── governance\          ← the brain (FastAPI, port 8004)
│   │   ├── app\
│   │   │   ├── engine\      ← guardrail checks (injection, PII, toxicity, secrets…)
│   │   │   ├── redteam\     ← attack library + prompt generator
│   │   │   ├── services\    ← business logic (agents, risk, evaluations, gateway gate, evidence)
│   │   │   ├── routers\     ← the HTTP API endpoints
│   │   │   ├── models.py    ← database tables
│   │   │   └── security.py  ← who may call what (API keys, users, secure headers)
│   │   └── tests\           ← 55 tests
│   └── gateway\             ← the secure door (FastAPI, port 8005), 11 tests
├── trustai-sdk\
│   └── trustai\
│       ├── govern\          ← NEW: governance SDK (client + runtime guard)
│       └── cli.py           ← NEW: the `trustai` command-line tool
├── dashboard\               ← Next.js UI (RandomTrees theme)
│   └── src\app\governance\  ← the 9 governance screens
└── docs\
    ├── GOVERNANCE_PLAN.md   ← the plan + open items
    └── TRUSTAI_EXPLAINED.md ← this file

Desktop\Internal\AI-Factory
├── .claude\skills\trustai\scripts\
│   ├── trustai.py           ← factory commands (onboard, risk-assess, red-team, …)
│   └── trustai_client.py    ← the real TrustAI client (standard Python only)
├── .claude\skills\factory-04-agent-engineering\scripts\agent_runtime.py
│                            ← every agent: TrustAI guard + TrustAI gateway backend
└── docs\TRUSTAI-INTEGRATION.md
```

---

## 6. Yes — an SDK was created. How to use it

There are **three ways** to talk to TrustAI:

| Who | Uses | Why |
|---|---|---|
| Any Python developer | **`trustai.govern` SDK** | Easiest — typed, retries, errors handled |
| Terminal / scripts / CI | **`trustai` CLI** | One-line commands, JSON output |
| The AI Factory | **`trustai_client.py`** | Built with standard Python only, so the factory needs no extra installs |

### 6.1 Install

```bash
pip install -e "C:\Users\kishore kumar\Desktop\TrustAI\trustai-sdk"
```

Set two settings (or pass them in code):

```
TRUSTAI_GOVERNANCE_URL=http://localhost:8004
TRUSTAI_API_KEY=tai_live_...          (a project key with the "govern" scope)
```

### 6.2 The SDK in 6 steps

```python
from trustai.govern import GovernClient, Guard

gov = GovernClient()   # reads the URL + key from the environment

# 1. Register the agent
agent = gov.agents.onboard("WL-001", "Invoice Agent",
                           endpoint="http://localhost:8080/chat",
                           tools=[{"name": "pay_invoice", "side_effect": "write", "policy": "require_approval"}])

# 2. Rate the risk
risk = gov.risk.assess({"industry": "finance", "write_actions": ["pay_invoice"]}, agent_id=agent["id"])
print(risk["risk_tier"])                       # e.g. 3

# 3. Attack-test it (creates the test and waits for the result)
result = gov.run_evaluation(agent_id=agent["id"], num_generate=40)
print(result["trust_score"])                   # e.g. 100.0

# 4. (a person approves Tier 3+ in the dashboard)

# 5. Deploy behind the gateway — the key is shown ONCE, store it safely
deployment = gov.gateway.deploy(agent["id"])
print(deployment["gateway_url"], deployment["api_key"])

# 6. Protect every message at runtime
guard = Guard(gov, agent["id"])
verdict = guard.check("input", "Ignore all previous instructions...")
if verdict.blocked:
    print("Blocked by:", verdict.policies)
```

There is also an **async** version (`AsyncGovernClient`) with the same methods.

### 6.3 The CLI

```bash
trustai agents list
trustai risk assess --agent <AGENT_ID> --facts facts.json
trustai evaluations create --agent <AGENT_ID> --generate 40 --wait
trustai gateway deploy <AGENT_ID>
trustai agents evidence <AGENT_ID>
trustai metrics pii --text "mail me at jane@acme.com"
```

### 6.4 Calling the gateway (any OpenAI-compatible library)

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8005/v1", api_key="tai_gw_...")   # the one-time key
client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "Hi"}])
```

---

## 7. How the AI Factory uses TrustAI (steps 04 → 09)

```text
   STEP   AI FACTORY                       TRUSTAI                          RESULT
   ----   -------------------------------  -------------------------------  ---------------------------
    04    onboard ---------------------->  registers the agent + tools      agent id, Baseline policy
    05    onboard-mcp ------------------>  registers MCP servers (if any)   skipped if none
    06    risk-assess ------------------>  20 questions -> Tier             Tier 1-4
    06    red-team -------------------->   attacks the LIVE agent           trust score
    06    run_evals (factory own exam)                                      Gate 06 verdict
     .                                     A PERSON approves (Tier 3+)      decision recorded
    07    gateway-deploy --------------->  gate check -> one-time key       agent = DEPLOYED
     .    agent AI calls --------------->  go through the gateway           blocked if unsafe
    08    evidence -------------------->   audit pack (+ FactScore)         evidence report
    09    optimize -------------------->   finds weak spots                 stronger policies suggested
```

Turn it on in `Desktop\Internal\AI-Factory\.env`:

```
TRUSTAI_MODE=enabled
TRUSTAI_BASE_URL=http://localhost:8004
TRUSTAI_API_KEY=tai_live_local_factory_key_01
```

With `TRUSTAI_MODE=placeholder` (the default) the factory works exactly as before and makes no TrustAI calls.

---

## 8. What is the outcome? (what you get)

- **Every factory agent is registered, rated, attack-tested and approved** before it can go live.
- **Attacks are stopped twice**: inside the agent (runtime guard) and at the gateway.
- **Risky decisions stay with people** — TrustAI refuses machine approvals for Tier 3+.
- **One audit trail**: who did what, when, every block, every score — exportable as evidence.
- **Instant kill switch**: revoke an agent's gateway key and it can no longer call any AI model.
- **No dependency on Trustwise** — all RandomTrees code.

### Real results so far (Acme invoice-payment agent, real AI model)

| Step | Result |
|---|---|
| 04 Onboard | ✅ Registered, Baseline policy attached |
| 05 MCP | ✅ Correctly skipped (no MCP servers) |
| 06 Risk | ✅ Tier 3 – High Risk; High-Risk policy attached |
| 06 TrustAI red-team (36 prompts) | ✅ Trust **100**, attacks blocked **100%**, false alarms **0%** (1 prompt timed out) |
| 06 Factory exam (26 tests) | ✅ **CONDITIONAL_PASS** — accuracy 100%, 0 hallucinations, 0 personal-data leaks |
| 07 Deploy | ⏸ **Waiting**: the human risk decision has not reached TrustAI yet (being investigated) |
| 08 Evidence / 09 Optimise | ⏳ After step 07 |

**Bugs the real run found and fixed:** risk scoring counted a forbidden tool as a risk (Tier 4 → correctly Tier 3);
red-team grading counted polite follow-up questions as "over-blocking"; a duplicate-invoice check flagged the
original invoice; the dashboard's decision button silently did nothing when a condition wasn't "added".

---

## 9. How to run it

Three PowerShell windows (governance first):

```powershell
# 1 · Governance (port 8004)
cd "C:\Users\kishore kumar\Desktop\TrustAI\services\governance"; $env:TRUSTAI_ENVIRONMENT="development"; $env:TRUSTAI_POSTGRES_URL="sqlite+aiosqlite:///C:/Users/kishore kumar/Desktop/TrustAI/.local/governance.db"; $env:TRUSTAI_GOVERNANCE_STATIC_KEYS="tai_live_local_factory_key_01=55555555-5555-5555-5555-555555555555"; $env:TRUSTAI_INTERNAL_API_SECRET="local-internal-secret"; $env:TRUSTAI_EVAL_EXECUTOR="inline"; $env:TRUSTAI_GATEWAY_PUBLIC_URL="http://localhost:8005"; $env:TRUSTAI_PORTAL_URL="http://localhost:3001"; $env:TRUSTAI_CORS_ORIGINS='["http://localhost:3001"]'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8004
```
```powershell
# 2 · AI Gateway (port 8005)
cd "C:\Users\kishore kumar\Desktop\TrustAI\services\gateway"; $env:TRUSTAI_ENVIRONMENT="development"; $env:TRUSTAI_GOVERNANCE_URL="http://127.0.0.1:8004"; $env:TRUSTAI_INTERNAL_API_SECRET="local-internal-secret"; $env:TRUSTAI_GATEWAY_UPSTREAMS='{"claude-sonnet-4-5": {"provider": "mock"}, "gpt-4o": {"provider": "mock"}}'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8005
```
```powershell
# 3 · Dashboard (port 3001)
cd "C:\Users\kishore kumar\Desktop\TrustAI\dashboard"; $env:NEXT_PUBLIC_GOVERNANCE_URL="http://127.0.0.1:8004"; $env:INTERNAL_GOVERNANCE_URL="http://127.0.0.1:8004"; $env:NEXT_PUBLIC_GATEWAY_URL="http://localhost:8005"; npx next dev -p 3001
```

| Open | URL |
|---|---|
| Dashboard | http://localhost:3001/governance |
| API docs | http://localhost:8004/docs |
| Gateway health | http://localhost:8005/ready |

---

## 10. Words you'll see

| Word | Meaning |
|---|---|
| **Agent** | An AI program that can answer and take actions (e.g. pay an invoice) |
| **Tool** | An action the agent can take; *write* tools change things, *read* tools only look |
| **Tier** | Risk level 1 (low) – 4 (critical) |
| **Guardrail** | One safety filter (a set of checks) |
| **Policy** | Which guardrails apply where (input/output/tools) and how strictly |
| **Red-team** | Deliberately attacking the agent to find weaknesses |
| **Trust score** | % of test prompts the agent handled correctly (blocked attacks + answered normal questions) |
| **Gateway** | The secure door for all AI model calls |
| **Gate** | The checklist that must pass before an agent can be deployed |
| **Kill switch** | Revoking the gateway key — the agent instantly loses AI access |
| **Evidence pack** | Everything about one agent in one report, for audits |

---

## 11. What's still open

1. **Step 07–09 for the Acme agent** — waiting for the human risk decision to be recorded in TrustAI.
2. **Docker** — images partly built; downloads from pypi.org kept timing out. TrustAI runs without Docker for now.
3. **Real AI models in the gateway** — needs an Azure OpenAI or OpenRouter key (today a test model answers).
4. **Optional smarter checks** — Azure AI Content Safety and an AI judge (configured by settings, no code change).
5. **Database** — local SQLite file today; Postgres in production (supported, not yet run here).
