# TrustAI — Complete Technical & Code-Level Architecture Documentation

This document provides comprehensive, function-by-function, and module-by-module technical documentation for the **TrustAI** enterprise GenAI monitoring, cost intelligence, and observability platform.

---

# Table of Contents
1. [System Architecture & Data Flow](#1-system-architecture--data-flow)
2. [TrustAI Python SDK (`trustai-sdk/`)](#2-trustai-python-sdk)
   - [`trustai/__init__.py`](#21-trustai__init__py)
   - [`trustai/models.py`](#22-trustaimodelspy)
   - [`trustai/client.py`](#23-trustaiclientpy)
   - [`trustai/decorators.py`](#24-trustaidecoratorspy)
   - [`trustai/connectors/base.py`](#25-trustaiconnectorsbasepy)
   - [`trustai/connectors/azure_app_insights.py`](#26-trustaiconnectorsazure_app_insightspy)
3. [Shared Library (`shared/`)](#3-shared-library)
   - [`shared/config.py`](#31-sharedconfigpy)
   - [`shared/models/db.py` (Metadata PostgreSQL)](#32-sharedmodelsdbpy)
   - [`shared/models/analytics_db.py` (Analytics TimescaleDB)](#33-sharedmodelsanalytics_dbpy)
   - [`shared/models/schemas.py` (Pydantic API Models)](#34-sharedmodelsschemaspy)
   - [`shared/db/session.py`](#35-shareddbsessionpy)
   - [`shared/auth/azure_ad.py`](#36-sharedauthazure_adpy)
   - [`shared/auth/rbac.py`](#37-sharedauthrbacpy)
4. [Ingestion Microservice (`services/ingestion/`)](#4-ingestion-microservice)
   - [`app/main.py`](#41-ingestion-appmainpy)
   - [`app/dependencies.py`](#42-ingestion-appdependenciespy)
   - [`app/routers/traces.py`](#43-ingestion-approuterstracespy)
   - [`app/middleware.py`](#44-ingestion-appmiddlewarepy)
5. [Processing Worker (`services/processor/`)](#5-processing-worker)
   - [`app/consumer.py`](#51-processor-appconsumerpy)
   - [`app/cost_engine.py`](#52-processor-appcost_enginepy)
   - [`app/enricher.py`](#53-processor-appenricherpy)
6. [Analytics API Microservice (`services/api/`)](#6-analytics-api-microservice)
   - [`app/routers/overview.py`](#61-api-overviewpy)
   - [`app/routers/clients.py`](#62-api-clientspy)
   - [`app/routers/projects.py`](#63-api-projectspy)
   - [`app/routers/agents.py`](#64-api-agentspy)
   - [`app/routers/traces.py`](#65-api-tracespy)
   - [`app/routers/cost.py`](#66-api-costpy)
   - [`app/routers/alerts.py`](#67-api-alertspy)
7. [Admin Microservice (`services/admin/`)](#7-admin-microservice)
   - [`app/routers/clients.py`](#71-admin-clientspy)
   - [`app/routers/projects.py`](#72-admin-projectspy)
   - [`app/routers/api_keys.py`](#73-admin-api_keyspy)
   - [`app/routers/pricing.py`](#74-admin-pricingpy)
8. [Dashboard Architecture (`dashboard/`)](#8-dashboard-architecture)
9. [Security & Production Hardening](#9-security--production-hardening)

---

# 1. System Architecture & Data Flow

TrustAI uses a decoupled, event-driven microservices architecture:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AI Application / Agent                          │
│                                                                        │
│   @trustai.agent("doc_proc")         @trustai.llm_call(model="gpt-4o") │
│   def run_pipeline(...):              def query_llm(...):              │
│       ...                                 return client.chat(...)      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Asynchronous background batch)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Ingestion Service (FastAPI :8001)                   │
│  - API Key Validation (SHA-256 hash lookup)                            │
│  - Redis Sliding-Window Rate Limiting (1,000 req/min)                 │
│  - Content Scrubbing/Masking (per-environment policy)                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      Azure Event Hub / Kafka                           │
│                      Topic: trustai-telemetry                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Processor Worker Service                         │
│  - Stream Consumer (Event Hub Batch Receiver)                         │
│  - Agent Auto-Discovery & ID Resolution                                │
│  - Real-time Cost Calculation via cached ModelPricing                  │
│  - Bulk insertion into TimescaleDB                                     │
└───────────────────────┬───────────────────────────────┬────────────────┘
                        ▼                               ▼
     ┌────────────────────────────┐          ┌───────────────────────────┐
     │  PostgreSQL (Metadata)     │          │ TimescaleDB (Analytics)   │
     │  - Clients & Projects      │          │ - spans (hypertables)     │
     │  - API Keys & Users (RBAC) │          │ - hourly_rollups          │
     │  - Model Pricing Catalog   │          │ - daily_rollups           │
     └─────────────▲──────────────┘          └─────────────▲─────────────┘
                   │                                       │
                   └───────────────────┬───────────────────┘
                                       │
┌──────────────────────────────────────┴─────────────────────────────────┐
│                      Analytics API (FastAPI :8002)                     │
│  - JWT Verification (Azure AD JWKS)                                    │
│  - Multi-tenant RBAC enforcement                                       │
│  - Tree-structured trace waterfall queries & Rollup aggregations       │
└──────────────────────────────────────▲─────────────────────────────────┘
                                       │
┌──────────────────────────────────────┴─────────────────────────────────┐
│                       Next.js 14 Enterprise UI                         │
│  - Company KPIs, Client/Project Drilldown, Cost Graphs, Trace Trees    │
└────────────────────────────────────────────────────────────────────────┘
```

---

# 2. TrustAI Python SDK

The SDK is a lightweight, zero-dependency tracing library installed into developer repositories via `pip install trustai`.

### 2.1 `trustai/__init__.py`
Exports the public API surface.

* **`init(api_key: str, project_id: str, environment: str = "production", ingest_url: str = "http://localhost:8001", content_capture_mode: str = "masked", agent_name: str | None = None, batch_size: int = 50, flush_interval_seconds: float = 5.0, **kwargs) -> TrustAIClient`**:
  Initializes the singleton `TrustAIClient` instance and sets `_decorators._client`.
* **`flush() -> None`**:
  Manually triggers an immediate synchronization of all buffered spans to the ingestion endpoint.
* **`shutdown() -> None`**:
  Flushes pending buffers and cleanly terminates the background daemon thread.
* **Exports**: `@trace`, `@agent`, `@llm_call`, `span()` context manager, `Span`, `LLMUsage`.

---

### 2.2 `trustai/models.py`
Defines provider-neutral data models serializable into TrustAI ingestion payloads.

* **`LLMUsage` (Pydantic BaseModel)**:
  * `input_tokens: int | None`
  * `output_tokens: int | None`
  * `total_tokens: int | None`
  * `cached_tokens: int | None`
  * `reasoning_tokens: int | None`
  * `cost_usd: float | None`
* **`Span` (Pydantic BaseModel)**:
  * `trace_id`: UUID hex string representing the entire distributed execution tree.
  * `span_id`: Unique 16-character identifier for this specific unit of execution.
  * `parent_span_id`: ID of the parent span (e.g. agent span containing LLM calls).
  * `span_name`: Function name or custom span label.
  * `span_kind`: Literal enum (`"llm"`, `"agent"`, `"tool"`, `"retrieval"`, `"internal"`).
  * `started_at` / `ended_at` / `duration_ms`: Execution timestamps and latency.
  * `provider` / `model_name` / `model_version` / `operation`: LLM engine details.
  * `usage`: `LLMUsage` instance.
  * `input_content` / `output_content`: Captured prompt/response (subject to PII masking).
  * `success: bool`, `error_type: str | None`, `error_message: str | None`: Status tracking.
  * `tags: dict[str, Any]` / `attributes: dict[str, Any]`: Custom developer telemetry tags.
  * **`finish(self, *, success: bool = True, error: Exception | None = None) -> None`**:
    Computes `ended_at`, sets `duration_ms = (ended_at - started_at).total_seconds() * 1000`, and extracts error details.
  * **`to_ingest_dict(self) -> dict[str, Any]`**:
    Flattens usage fields into top-level dictionary keys for HTTP transport.

---

### 2.3 `trustai/client.py`
Provides thread-safe in-memory buffering and non-blocking background transport.

* **`TrustAIClient` Class**:
  * **`__init__(...)`**: Initializes internal buffer `self._buffer: list[Span]`, `threading.Lock()`, and spawns the daemon thread `_flush_thread` running `self._background_flush()`. Registers `atexit.register(self.flush)`.
  * **`start_span(name: str, kind: str = "internal", parent_span_id: str | None = None, trace_id: str | None = None, tags: dict | None = None) -> Span`**:
    Constructs and returns an active `Span` populated with the current capture settings.
  * **`finish_span(span: Span, success: bool = True, error: Exception | None = None, input_content: str | None = None, output_content: str | None = None) -> None`**:
    Finalizes the span, applies `_mask_content()` if `content_capture_mode == "masked"`, acquires the thread lock, appends the span to `_buffer`, and triggers `_drain()` if `len(_buffer) >= batch_size`.
  * **`flush() -> None`**:
    Synchronously drains all queued spans.
  * **`_drain() -> None`**:
    Copies pending spans and spawns a background thread calling `_send_batch()`.
  * **`_send_batch(spans: list[Span]) -> None`**:
    Executes an HTTP POST request to `{ingest_url}/v1/traces` with exponential backoff (`max_retries = 3`).
* **`_mask_content(text: str | None) -> str | None`**:
  Applies regex sanitizers replacing Email addresses (`[EMAIL]`), Credit Card numbers (`[CARD]`), Phone numbers (`[PHONE]`), and IPv4 addresses (`[IP]`).

---

### 2.4 `trustai/decorators.py`
High-level decorators wrapping developer functions.

* **`@trustai.trace(name=None, kind="internal", tags=None, capture_args=False)`**:
  Wraps any sync or async function into a monitored span. If `capture_args=True`, serializes arguments using `_capture_args()`.
* **`@trustai.agent(name=None, tags=None)`**:
  Syntactic sugar for `@trustai.trace(kind="agent")`. Marks the root span of an agent workflow.
* **`@trustai.llm_call(name=None, model=None, provider=None, operation="chat")`**:
  Specialized wrapper for LLM calls. Intercepts OpenAI/Azure OpenAI responses, automatically extracting:
  * Prompt, completion, total, cached, and reasoning tokens (`usage_obj`).
  * Finish reason (`choices[0].finish_reason`).
  * Model deployment name.
  * Local cost estimation (`_compute_cost()`).
  * Captures `messages` parameter as input text and response text as output.
* **`trustai.span(name: str, kind: str = "internal", tags: dict | None = None)` Context Manager**:
  Enables block-scoped spans:
  ```python
  with trustai.span("retrieval_step", kind="retrieval") as sp:
      sp.tags["query"] = "sample"
      results = search()
  ```

---

### 2.5 `trustai/connectors/base.py`
Defines the standard interface for PULL-mode data ingestion from external cloud providers.

* **`BaseConnector` (Abstract Base Class)**:
  * **`provider_name -> str`**: Abstract property returning the provider key.
  * **`validate_config() -> bool`**: Tests connectivity/credentials.
  * **`fetch_raw_spans(since: datetime, until: datetime, project_filter, limit) -> list[dict]`**: Pulls raw logs from cloud store.
  * **`normalise(raw_spans: list[dict]) -> list[Span]`**: Transforms provider-specific telemetry schemas into standardized `Span` instances.
  * **`fetch_and_normalise(...) -> list[Span]`**: Pipeline execution method.

---

### 2.6 `trustai/connectors/azure_app_insights.py`
Azure Monitor / Application Insights Log Analytics integration.

* **`AzureAppInsightsConnector(BaseConnector)`**:
  * **`_GENAI_SPANS_KQL`**: Parameterized Kusto Query Language (KQL) query querying `dependencies` and `requests` where `customDimensions has "gen_ai.system"`.
  * **`_get_auth_headers()`**: Resolves Azure AD OAuth2 Token or API Key.
  * **`validate_config()`**: Executes a minimal test query (`traces | take 1`).
  * **`fetch_raw_spans(...)`**: Dispatches KQL queries to `https://api.loganalytics.io/v1/workspaces/{workspace_id}/query`.
  * **`normalise(raw_spans)`**: Unpacks `customDimensions`, mapping `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `cost_usd`, and `duration_ms` into standardized `Span` instances.

---

# 3. Shared Library (`shared/`)

The `trustai-shared` package contains core configurations, database models, session factories, and security logic.

### 3.1 `shared/config.py`
Pydantic `BaseSettings` classes loaded from environment variables:
* **`DatabaseSettings`**: `postgres_url`, `analytics_db_url`, pool sizing.
* **`RedisSettings`**: `redis_url`.
* **`AzureADSettings`**: `tenant_id`, `client_id`, `client_secret`, `authority`, `api_scope`, `audience`.
* **`EventHubSettings`**: `connection_string`, `eventhub_name`, `consumer_group`, `checkpoint_store_url`.
* **`AppInsightsSettings`**: `connection_string`, `workspace_id`, `workspace_key`.
* **`JWTSettings`**: `secret_key`, `algorithm`, expiration durations.
* **`get_settings() -> BaseServiceSettings`**: `@lru_cache`-wrapped settings getter.

---

### 3.2 `shared/models/db.py` (Metadata Store)
SQLAlchemy 2.0 ORM models for PostgreSQL:
* **`Client`**: Represents a tenant (external customer or internal department).
  * Fields: `id`, `name`, `slug`, `client_type` (`external` | `internal`), `monthly_budget_usd`, `is_active`, timestamps.
  * Relations: `projects`, `users`, `alert_rules`.
* **`Project`**: Represents an AI application or workload.
  * Fields: `id`, `client_id` (FK), `name`, `slug`, `content_capture_mode` (`full` | `masked` | `disabled`), `content_capture_overrides` (JSONB mapping environment to mode), `monthly_budget_usd`, `tags`.
  * Method: `get_content_capture_mode(environment: str) -> ContentCaptureMode`.
* **`Agent`**: Represents a specific agent or tool. Supports hierarchy via `parent_id`.
* **`ApiKey`**: Stores project SDK authentication keys.
  * Fields: `key_prefix`, `key_hash` (SHA-256), `status` (`active` | `revoked` | `expired`), `scopes`, `expires_at`, `last_used_at`.
* **`User` / `UserClientRole` / `UserProjectRole`**: Azure AD-linked user profiles and RBAC role assignments (`super_admin`, `client_admin`, `developer`, `project_viewer`).
* **`ModelPricing`**: Provider-neutral model pricing database.
  * Fields: `provider`, `model_name`, `input_price_per_1m`, `output_price_per_1m`, `cached_input_price_per_1m`, `reasoning_price_per_1m`.
* **`Connector`**: Configured cloud log pull integrations.
* **`AlertRule` / `FiredAlert`**: Threshold alert configurations and triggered incidents.
* **`AuditLog`**: Immutable ledger of administrative actions.

---

### 3.3 `shared/models/analytics_db.py` (Analytics Store)
Optimized for TimescaleDB / Time-series PostgreSQL:
* **`SpanRecord`**: Individual span telemetry table.
  * Indices: `(trace_id)`, `(project_id, environment, timestamp)`, `(client_id, timestamp)`, `(model_name, timestamp)`.
* **`HourlyRollup`**: Pre-aggregated metrics rolled up by hour, client, project, agent, and model.
  * Fields: `total_calls`, `successful_calls`, `failed_calls`, `total_tokens`, `total_cost_usd`, `avg_duration_ms`, `p50_duration_ms`, `p95_duration_ms`, `p99_duration_ms`.
* **`DailyRollup`**: Daily aggregated metrics table for dashboard reporting.

---

### 3.4 `shared/models/schemas.py`
Pydantic v2 schemas:
* **Ingestion**: `IngestSpan`, `IngestBatch`.
* **Client/Project**: `ClientCreate`, `ClientUpdate`, `ClientResponse`, `ProjectCreate`, `ProjectUpdate`, `ProjectResponse`.
* **API Keys**: `ApiKeyCreate`, `ApiKeyCreateResponse` (includes raw key once), `ApiKeyResponse`.
* **Analytics**: `OverviewMetrics`, `CostBreakdown`, `SpanDetail` (recursive tree model), `PaginatedResponse`.
* **Pricing/Alerts**: `ModelPricingCreate`, `ModelPricingResponse`, `AlertRuleCreate`, `FiredAlertResponse`.

---

### 3.5 `shared/db/session.py`
Async database engine configuration:
* `metadata_engine` & `MetadataSession`: Async engine for metadata database.
* `analytics_engine` & `AnalyticsSession`: Async engine for time-series analytics database.
* Dependency providers: `metadata_session_dep()`, `analytics_session_dep()`.

---

### 3.6 `shared/auth/azure_ad.py`
Azure AD / Entra ID token verification middleware:
* **`_get_jwks_uri()` & `_get_signing_keys()`**: Fetches and caches Microsoft's public keys from `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration`.
* **`_validate_azure_token(token: str) -> dict`**: Validates signature, expiration, and audience via RS256 cryptography.
* **`get_azure_claims(credentials)`**: FastAPI dependency injecting decoded `AzureADClaims`.

---

### 3.7 `shared/auth/rbac.py`
RBAC enforcement dependencies:
* **`require_super_admin()`**: Asserts `user.is_super_admin == True`.
* **`require_client_access(min_role)`**: Validates user membership on the requested `client_id`.
* **`require_project_access(min_role)`**: Validates user permission on `project_id` or inherited from the parent client.

---

# 4. Ingestion Microservice (`services/ingestion/`)

High-throughput, stateless FastAPI service responsible for receiving incoming spans from the SDK.

### 4.1 `app/dependencies.py`
* **`get_authenticated_project(x_api_key, session, redis) -> AuthenticatedProject`**:
  1. Computes SHA-256 hash of `X-API-Key`.
  2. Queries `ApiKey` in database.
  3. Verifies `status == ACTIVE` and non-expired.
  4. Calls `_check_rate_limit()` against Redis.
  5. Updates `last_used_at` timestamp.
* **`_check_rate_limit(key_prefix: str, redis: Redis)`**:
  Sliding-window rate limiter using Redis sorted sets (`ZREMRANGEBYSCORE`, `ZADD`, `ZCARD`).
* **`publish_to_eventhub(producer, payload, partition_key)`**:
  Batches and publishes JSON telemetry payloads to Azure Event Hub.

### 4.2 `app/routers/traces.py`
* **`POST /v1/traces` (`ingest_traces`)**:
  1. Receives `IngestBatch`.
  2. Evaluates project's `content_capture_mode` for the given environment.
  3. Strips input/output payloads if `content_capture_mode == disabled`.
  4. Packages enriched payload with `client_id` and `batch_id`.
  5. Publishes to Azure Event Hub partitioned by `project_id`.
  6. Returns HTTP 202 Accepted.

---

# 5. Processing Worker (`services/processor/`)

Asynchronous worker consuming messages from Azure Event Hub and persisting normalized data.

### 5.1 `app/consumer.py`
* **`start_consumer()`**: Initializes `EventHubConsumerClient` with `BlobCheckpointStore`.
* **`process_event_batch(events)`**: Deserializes JSON payloads.
* **`_process_payload(payload, analytics_db, meta_db)`**:
  1. Resolves `agent_id` via `resolve_agent_id()`.
  2. Calculates cost if missing via `compute_span_cost()`.
  3. Instantiates `SpanRecord` objects.
  4. Executes bulk database write (`analytics_db.add_all(records)`).

### 5.2 `app/cost_engine.py`
* **`compute_span_cost(session, provider, model_name, input_tokens, output_tokens, cached_tokens) -> float`**:
  Calculates USD cost based on `ModelPricing` entries:
  $$\text{Cost} = \frac{\text{uncached\_input} \times P_{\text{input}} + \text{cached\_input} \times P_{\text{cached}} + \text{output} \times P_{\text{output}}}{1,000,000}$$
  Maintains an in-memory pricing cache `_pricing_cache` to minimize database queries.

### 5.3 `app/enricher.py`
* **`resolve_agent_id(session, project_id, agent_name) -> uuid.UUID`**:
  Auto-discovers agents: queries `Agent` by slug; if not found, automatically creates a new `Agent` record.

---

# 6. Analytics API Microservice (`services/api/`)

BFF (Backend-For-Frontend) serving data to the dashboard.

### 6.1 `app/routers/overview.py`
* **`GET /api/v1/overview`**:
  Returns `OverviewMetrics` calculating total spend, call volume, token consumption, error rates, P95 latencies, and period-over-period trend percentages.

### 6.2 `app/routers/clients.py`
* **`GET /api/v1/clients`**: Paginated client listings enriched with 7-day spend, call volume, and project counts.
* **`GET /api/v1/clients/{client_id}`**: Detailed client summary.

### 6.3 `app/routers/projects.py`
* **`GET /api/v1/clients/{client_id}/projects`**: Project listings with usage stats.
* **`GET /api/v1/projects/{project_id}`**: Single project details.

### 6.4 `app/routers/agents.py`
* **`GET /api/v1/projects/{project_id}/agents`**: Agent breakdown with cost, error rate, and average execution latency.

### 6.5 `app/routers/traces.py`
* **`GET /api/v1/projects/{project_id}/traces`**: Filterable, paginated trace list.
* **`GET /api/v1/traces/{trace_id}`**: Reconstructs hierarchical execution trees (`SpanDetail.children`) from flat span records for trace waterfall visualization.

### 6.6 `app/routers/cost.py`
* **`GET /api/v1/cost/breakdown`**:
  Aggregates spend across 5 dimensions: `by_client`, `by_project`, `by_model`, `by_provider`, and `by_environment`, plus time-series daily metrics.

### 6.7 `app/routers/alerts.py`
* **`GET /api/v1/alerts`**, **`PATCH /api/v1/alerts/{id}/acknowledge`**, **`PATCH /api/v1/alerts/{id}/resolve`**: Alert management workflow endpoints.

---

# 7. Admin Microservice (`services/admin/`)

Manages administrative workflows, credentials, and configurations.

### 7.1 `app/routers/api_keys.py`
* **`POST /api/v1/projects/{project_id}/api-keys`**:
  Generates a cryptographically secure key `tai_live_<token_urlsafe(32)>`. Computes SHA-256 hash for storage, returns the plaintext key once to the caller, and logs an entry in `AuditLog`.
* **`DELETE /api/v1/api-keys/{key_id}`**: Revokes active API key.

### 7.2 `app/routers/pricing.py`
* **`GET /api/v1/pricing/models`**: Lists active model prices.
* **`POST /api/v1/pricing/models`**: Creates or updates model token pricing.
* **`POST /api/v1/pricing/models/seed`**: Seeds default pricing catalog for GPT-4o, GPT-4o-mini, O1-preview, and GPT-4-turbo.

---

# 8. Dashboard Architecture (`dashboard/`)

Built with **Next.js 14 App Router**, **TypeScript**, **Tailwind CSS**, and **Recharts**:

* **`src/app/globals.css`**: Custom dark-mode design system with CSS custom properties (`--brand-500`, `--surface-0` through `--surface-4`, `--glass-bg`), glassmorphism card utilities (`.glass-card`), and badge presets.
* **`src/app/page.tsx`**: Executive overview dashboard displaying KPI cards, cost trend area charts, model distribution pie charts, and top-spending projects.
* **`src/app/clients/page.tsx`**: Client directory with budget utilization indicators.
* **`src/app/cost/page.tsx`**: Multi-dimensional cost intelligence views.
* **`src/app/alerts/page.tsx`**: Incident center with visual severity indicators and resolution actions.
* **`src/app/settings/onboarding/page.tsx`**: 5-step guided wizard for registering clients, projects, connectors, and testing SDK installations.

---

# 9. Security & Production Hardening

1. **Authentication**:
   * **Dashboard & APIs**: OAuth2 / OpenID Connect with Azure AD (Entra ID) using RSA256 JWKS verification.
   * **SDK Transport**: Cryptographic API keys stored as SHA-256 hashes (`tai_live_...`).
2. **Authorization (RBAC)**:
   * 4-tier role hierarchy: `super_admin` > `client_admin` > `developer` > `project_viewer`.
3. **Data Privacy**:
   * Configurable prompt/response capture (`full`, `masked`, `disabled`).
   * Built-in PII redaction rules for emails, phone numbers, credit card numbers, and IP addresses.
4. **Resilience**:
   * Redis-backed sliding-window rate limiting prevents API abuse.
   * Event-driven decoupling using Azure Event Hub ensures zero loss during peak ingestion spikes.
   * Read queries leverage pre-aggregated `DailyRollup` tables to maintain sub-100ms dashboard latency.
