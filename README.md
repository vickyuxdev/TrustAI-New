# TrustAI — Enterprise GenAI Observability Platform

> Production-grade, multi-tenant monitoring, cost intelligence, and traceability for your entire AI company.

![TrustAI](https://img.shields.io/badge/TrustAI-v0.1.0-3b82f6?style=for-the-badge)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi)
![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=for-the-badge&logo=next.js)
![Azure](https://img.shields.io/badge/Azure-Container%20Apps-0078D4?style=for-the-badge&logo=microsoft-azure)

---

## What is TrustAI?

TrustAI is an enterprise-grade observability platform for companies building AI products at scale. It gives you:

- **Full-stack GenAI tracing** — every LLM call, agent run, and tool invocation, captured automatically
- **Cost intelligence** — per-call cost computed from model pricing; drill down by client → project → agent → call
- **Multi-tenant RBAC** — manage external clients and internal teams with role-scoped access
- **Provider-neutral architecture** — Azure App Insights today; connector interfaces ready for AWS Bedrock, Databricks, and more
- **Developer SDK** — two lines of Python and any project is instrumented

---

## Architecture

```
Developer Python App
    │  pip install trustai
    │  trustai.init(api_key=..., project_id=...)
    │  @trustai.llm_call(model="gpt-4o")
    ▼
Ingestion Service (FastAPI :8001)
    │  API key auth + rate limiting (Redis)
    │  Content capture enforcement (per-project config)
    ▼
Azure Event Hub ──────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
                                                                                                                              ▼
                                                                                                                    Processor Worker
                                                                                                                         │  Enrich + cost compute
                                                                                                                         │  Hourly/daily rollups
                                                                                                                         ▼
                                                                                                    ┌──────────────────────────────────┐
                                                                                                    │   Analytics DB (TimescaleDB)     │
                                                                                                    │   spans · hourly_rollups          │
                                                                                                    │   daily_rollups                   │
                                                                                                    └─────────────┬────────────────────┘
                                                                                                                  │
Azure App Insights ──────────── (pull connector) ──────────────────────────────────────────────────────────────────┘
    (raw OTEL telemetry)

Analytics API (FastAPI :8002) ◄──── Next.js Dashboard (:3000)
Admin Service  (FastAPI :8003)       Premium enterprise UI
```

---

## Governance (agents: onboard, risk, guardrails, red-team, AI gateway)

TrustAI also governs the agents it observes - see **[services/governance/README.md](services/governance/README.md)**
and the implementation plan [docs/GOVERNANCE_PLAN.md](docs/GOVERNANCE_PLAN.md).

| Service | URL |
|---|---|
| Governance API | http://localhost:8004/docs |
| AI Gateway (OpenAI-compatible) | http://localhost:8005/v1 |
| Governance dashboard | http://localhost:3000/governance |

## Quick Start (Local Dev)

### Prerequisites
- Docker Desktop
- Node.js 20+
- Python 3.11+
- Azure AD App Registration (for SSO)

### 1. Clone & Configure

```bash
git clone https://github.com/yourcompany/trustai
cd TrustAI
cp .env.example .env
# Edit .env with your Azure AD credentials and connection strings
```

### 2. Start Everything

```bash
docker compose up -d
```

Services start at:
| Service       | URL                      |
|---------------|--------------------------|
| Dashboard     | http://localhost:3000    |
| Analytics API | http://localhost:8002/docs |
| Admin Service | http://localhost:8003/docs |
| Ingestion API | http://localhost:8001/docs |

### 3. Seed Model Pricing

```bash
curl -X POST http://localhost:8003/api/v1/pricing/models/seed \
  -H "Authorization: Bearer <your-azure-ad-token>"
```

### 4. Install the SDK in your project

```bash
pip install trustai
```

```python
import trustai

trustai.init(
    api_key="tai_live_xxx",    # Generate in TrustAI Dashboard → Settings → API Keys
    project_id="proj_xxx",     # From TrustAI Dashboard → Projects
    environment="production",
    content_capture_mode="masked",
)

@trustai.llm_call(model="gpt-4o", provider="azure_openai")
def call_gpt(client, messages):
    return client.chat.completions.create(model="gpt-4o", messages=messages)
```

---

## Project Structure

```
TrustAI/
├── trustai-sdk/               # Python SDK (pip install trustai)
│   └── trustai/
│       ├── __init__.py        # Public API: init(), trace, agent, llm_call, span
│       ├── client.py          # Thread-safe batching client
│       ├── decorators.py      # @trace, @agent, @llm_call, span()
│       ├── models.py          # Provider-neutral Span, LLMUsage, AgentRun
│       └── connectors/
│           ├── base.py        # Abstract BaseConnector interface
│           └── azure_app_insights.py  # Azure App Insights PULL connector
│
├── shared/                    # Shared Python library
│   └── shared/
│       ├── config.py          # Pydantic BaseSettings
│       ├── models/
│       │   ├── db.py          # SQLAlchemy ORM (metadata store)
│       │   ├── analytics_db.py # TimescaleDB models (analytics store)
│       │   └── schemas.py     # Pydantic v2 request/response schemas
│       ├── db/session.py      # Async session factories
│       └── auth/
│           ├── azure_ad.py    # Azure AD JWT validation
│           └── rbac.py        # Role-based access control
│
├── services/
│   ├── ingestion/             # SDK → Event Hub receiver (FastAPI :8001)
│   ├── api/                   # Analytics BFF (FastAPI :8002)
│   ├── admin/                 # Admin CRUD (FastAPI :8003)
│   ├── processor/             # Event Hub consumer + aggregator
│   └── auth/                  # Azure AD OIDC service
│
├── dashboard/                 # Next.js 16 console — observability + governance (:3000)
│
├── infra/
│   ├── azure/container-apps/  # Azure Container Apps manifests
│   └── azure/bicep/           # Infrastructure as Code
│
├── docker-compose.yml         # Full local dev stack
├── .env.example               # Environment variable template
└── tracing_utils.py           # Original file — migrated into SDK
```

---

## SDK Decorator Reference

```python
# Global init
trustai.init(api_key, project_id, environment, content_capture_mode)

# Decorators (sync + async)
@trustai.agent("agent_name")              # Root agent span
@trustai.llm_call(model="gpt-4o")        # LLM call with token/cost tracking
@trustai.trace("step_name")              # Generic span

# Context manager
with trustai.span("custom_step") as sp:
    sp.tags["doc_type"] = "invoice"
    result = do_work()

# Explicit flush (e.g., end of notebook cell)
trustai.flush()
```

---

## Connector Interface (Multi-cloud)

Implementing a new provider connector:

```python
from trustai.connectors.base import BaseConnector

class MyCustomConnector(BaseConnector):
    @property
    def provider_name(self) -> str:
        return "my_provider"

    async def validate_config(self) -> bool:
        # Test connectivity
        ...

    async def fetch_raw_spans(self, since, until, project_filter, limit) -> list[dict]:
        # Fetch raw telemetry from provider
        ...

    async def normalise(self, raw_spans) -> list[Span]:
        # Transform to TrustAI Span objects
        ...
```

Supported connectors:
| Provider | Status |
|---|---|
| Azure Application Insights | ✅ Implemented |
| Custom OTEL (push via SDK) | ✅ Implemented |
| AWS Bedrock / CloudWatch | 🔧 Interface defined, not implemented |
| Databricks MLflow | 🔧 Interface defined, not implemented |

---

## Security

- **API Keys**: SHA-256 hashed, never stored plain. Shown once on generation.
- **Auth**: Azure AD / Entra ID SSO with JWKS-based offline JWT validation.
- **RBAC**: 4-level hierarchy — `super_admin` > `client_admin` > `developer` > `project_viewer`.
- **Rate Limiting**: Redis sliding window per API key (1000 req/min).
- **Content Capture**: Configurable per project + per environment (`full | masked | disabled`).
- **Secrets**: Azure Key Vault references only — no raw secrets in DB.
- **Audit Log**: Every admin action logged to immutable `audit_logs` table.

---

## Roadmap

- [ ] Aggregation worker (hourly/daily rollups)
- [ ] Alert rule engine with Teams/Slack notifications
- [ ] Trace waterfall UI page
- [ ] Agent drill-down page
- [ ] AWS Bedrock connector implementation
- [ ] Databricks MLflow connector implementation
- [ ] PDF cost report generation
- [ ] Azure Container Apps Terraform/Bicep IaC
- [ ] CI/CD pipelines (GitHub Actions)
