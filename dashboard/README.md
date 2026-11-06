# TrustAI Dashboard

The web console for TrustAI — AI observability (cost, usage, traces, alerts) and AI governance (agent registry, risk assessments, guardrails, red-teaming, AI gateway) in one place.

Built with **Next.js 16 (App Router)**, React 19 and TanStack Query. Styling is a hand-written design system (`src/app/globals.css`) using the Evergreen theme, a single typeface (Inter, self-hosted) and full light/dark support. Charts are lightweight SVG components — no charting library.

## Screens

| Area | Route | What it shows |
|---|---|---|
| Overview | `/` | Spend, calls, tokens, error rate, latency, daily spend, where spend goes, top projects, live activity |
| | `/cost` | Cost insights by model, provider, environment, project, agent and client |
| | `/alerts` | Fired alerts (acknowledge / resolve) and alert rules |
| Observability | `/projects`, `/projects/[id]` | Projects, budgets, per-project spend, agents and API keys |
| | `/agents` | Agents discovered from telemetry |
| | `/traces` | Live span feed with filters and a trace waterfall |
| Governance | `/governance` | Lifecycle pipeline, risk tiers, pending decisions, red-team runs, audit trail |
| | `/governance/agents`, `/governance/agents/[id]` | Agent registry, onboarding, lifecycle changes, policies, red-team, gateway, evidence pack |
| | `/governance/risk`, `/governance/risk/[id]` | Risk questionnaire (EU AI Act / NIST AI RMF / ISO 42001), classification and human decision |
| | `/governance/policies` | Policies, guardrails, evaluator catalog, playground, recent guardrail decisions |
| | `/governance/evaluations`, `/governance/evaluations/[id]` | Red-team runs, trust score, per-category and per-guardrail results, every prompt |
| | `/governance/gateway` | AI gateway deployments and models |
| | `/governance/events` | Audit events |
| Settings | `/settings/connectors` | Cloud connectors (Azure OpenAI, App Insights, AI Foundry, AWS Bedrock) |
| | `/settings/onboarding` | SDK setup and API keys |
| | `/settings/pricing` | Model prices used to cost every call |

## How it talks to the backend

The browser only calls the dashboard itself. Three server-side proxies forward requests to the services:

| Proxy | Service | Environment variable (first match wins) | Default |
|---|---|---|---|
| `/api/backend/*` | Analytics API | `INTERNAL_API_URL`, `NEXT_PUBLIC_API_URL` | `http://localhost:8002` |
| `/api/admin/*` | Admin service | `INTERNAL_ADMIN_URL`, `NEXT_PUBLIC_ADMIN_URL` | `http://localhost:8003` |
| `/api/governance/*` | Governance service | `INTERNAL_GOVERNANCE_URL`, `NEXT_PUBLIC_GOVERNANCE_URL` | `http://localhost:8004` |

Each proxy appends `/api/v1/` and forwards the `Authorization` header and query string.

## Run it

```bash
npm install
npm run dev        # http://localhost:3000
```

With the full stack: `docker compose up` from the repository root (the compose file sets the `INTERNAL_*` URLs).

## Checks

```bash
npm run lint       # ESLint (next/core-web-vitals + TypeScript)
npx tsc --noEmit   # type check
npm test           # Vitest unit tests
npm run build      # production build
```

## Code map

```
src/
  app/                 routes (one folder per screen) + API proxies in app/api
  components/          ui.tsx (cards, KPIs, pills, tables, modals…), charts.tsx (SVG charts),
                       blocks.tsx, gov.tsx (governance badges), shell/ (sidebar, top bar, time range)
  lib/                 api.ts (analytics + admin client & hooks), governance.ts (governance client & hooks),
                       format.ts, series.ts, timeRange.ts
```
