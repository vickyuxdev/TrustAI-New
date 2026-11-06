"use client";
/**
 * Typed client for the Analytics API (/api/backend → services/api) and the Admin service
 * (/api/admin → services/admin). Shapes mirror shared/models/schemas.py and the routers.
 */
import { useMutation, useQueries, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { timeRangeQuery, type TimeRangeSpec } from "@/lib/timeRange";

// ─── Types ───────────────────────────────────────────────────────────────

export interface Paginated<T> { total: number; page: number; page_size: number; items: T[] }

export interface OverviewMetrics {
  period_start: string;
  period_end: string;
  total_cost_usd: number;
  total_calls: number;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  error_rate: number;          // 0–100
  avg_latency_ms: number;
  p95_latency_ms: number;
  active_projects: number;
  active_agents: number;
  cost_trend_pct: number;
  calls_trend_pct: number;
}

export interface Dim {
  dimension: string;
  total_cost_usd: number;
  total_calls: number;
  total_tokens: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
}
export interface TopProject extends Dim { name: string; error_rate: number }
export interface DayPoint { date: string; total_cost_usd: number; total_calls: number; total_tokens: number }
export interface CostBreakdown {
  by_client: Dim[];
  by_project: Dim[];
  by_model: Dim[];
  by_provider: Dim[];
  by_environment: Dim[];
  by_agent: Dim[];
  time_series: DayPoint[];
  top_projects: TopProject[];
}

export type ClientType = "external" | "internal";
export interface Client {
  id: string;
  name: string;
  slug: string;
  client_type: ClientType;
  description: string | null;
  is_active: boolean;
  monthly_budget_usd: number | null;
  created_at: string;
  total_cost_usd: number | null;
  total_calls: number | null;
  active_projects: number | null;
}

export type CaptureMode = "full" | "masked" | "disabled";
export interface Project {
  id: string;
  client_id: string;
  name: string;
  slug: string;
  description: string | null;
  content_capture_mode: CaptureMode;
  content_capture_overrides: Record<string, CaptureMode>;
  is_active: boolean;
  monthly_budget_usd: number | null;
  tags: string[];
  created_at: string;
  total_cost_usd: number | null;
  total_calls: number | null;
}

export interface ObservedAgent {
  id: string;
  name: string;
  slug: string;
  span_name?: string;
  project_id: string | null;
  project_name?: string | null;
  client_name?: string | null;
  agent_type: string;
  total_calls: number;
  total_tokens?: number;
  total_cost_usd: number;
  error_rate: number;          // /agents: 0–1 fraction · /projects/{id}/agents: 0–100
  avg_duration_ms: number | null;
  last_active?: string | null;
}

export interface Span {
  id: string;
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  span_name: string;
  span_kind: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  provider: string | null;
  model_name: string | null;
  operation: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cost_usd: number | null;
  input_content: string | null;
  output_content: string | null;
  content_capture_mode: string | null;
  success: boolean;
  error_type: string | null;
  error_message: string | null;
  finish_reason: string | null;
  tags: Record<string, unknown>;
  attributes: Record<string, unknown>;
  client_id: string | null;
  project_id: string | null;
  source_provider: string | null;
  connector_id: string | null;
  connector_name: string | null;
  children: Span[];
}

export type Severity = "info" | "warning" | "critical";
export type AlertStatus = "active" | "acknowledged" | "resolved";
export interface AlertRule {
  id: string;
  name: string;
  metric: string;
  operator: "gt" | "lt" | "gte" | "lte" | "eq";
  threshold: number;
  window_minutes: number;
  severity: Severity;
  notification_channels: string[];
  is_active: boolean;
  created_at: string;
}
export interface FiredAlert {
  id: string;
  rule_id: string;
  status: AlertStatus;
  triggered_value: number;
  message: string;
  triggered_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export type ConnectorProvider = "azure_openai" | "azure_app_insights" | "azure_foundry" | "aws_bedrock" | "gcp_vertex" | "databricks_mlflow";
export interface Connector {
  id: string;
  client_id: string;
  project_id: string | null;
  name: string;
  provider: ConnectorProvider;
  is_active: boolean;
  config: Record<string, unknown>;
  sync_interval_minutes: number;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_error: string | null;
  last_sync_records: number | null;
  created_at: string;
  updated_at: string;
  credential_keys: string[];
}
export interface ConnectorTestResult { success: boolean; message: string; details: Record<string, unknown> }
export interface SyncResult { connector_id: string; status: string; message: string; records_written: number }

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  status: "active" | "revoked" | "expired";
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}
export interface ApiKeyCreated { id: string; name: string; key_prefix: string; raw_key: string; scopes: string[]; created_at: string }

export interface ModelPricing {
  id: string;
  provider: string;
  model_name: string;
  model_version: string | null;
  input_price_per_1m: number;
  output_price_per_1m: number;
  cached_input_price_per_1m: number | null;
  reasoning_price_per_1m: number | null;
  effective_from: string;
  is_active: boolean;
}

// ─── Transport ───────────────────────────────────────────────────────────

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
  get unreachable(): boolean {
    return this.status === 0 || this.status === 502 || this.status === 503 || this.status === 504;
  }
}

function messageOf(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const d = (body as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : JSON.stringify(x))).join("; ");
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
    const e = (body as { error?: unknown }).error;
    if (typeof e === "string") return e;
  }
  return `Request failed (${status})`;
}

async function call<T>(base: "backend" | "admin", path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/${base}/${path.replace(/^\//, "")}`, {
      method: init?.method ?? "GET",
      headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Network error: the dashboard server could not be reached", null);
  }
  if (res.status === 204) return null as T;
  const text = await res.text();
  let body: unknown = null;
  if (text) { try { body = JSON.parse(text); } catch { body = text; } }
  if (!res.ok) throw new ApiError(res.status, messageOf(body, res.status), body);
  return body as T;
}
export const api = <T,>(path: string, init?: { method?: string; body?: unknown }) => call<T>("backend", path, init);
export const admin = <T,>(path: string, init?: { method?: string; body?: unknown }) => call<T>("admin", path, init);

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

function retry(count: number, err: unknown): boolean {
  if (err instanceof ApiError && (err.status < 500 || err.unreachable)) return false;
  return count < 2;
}

/** Range params for a query. `key` (from useTimeRange) keeps cache keys stable for presets. */
const rq = (spec: TimeRangeSpec) => timeRangeQuery(spec);

// ─── Analytics queries ──────────────────────────────────────────────────

export const useOverviewMetrics = (spec: TimeRangeSpec, key: string) =>
  useQuery<OverviewMetrics, ApiError>({ queryKey: ["overview", key], queryFn: () => api(`overview${qs(rq(spec))}`), retry, refetchInterval: 60_000 });

export interface CostFilters { project_id?: string; environment?: string; client_id?: string }
/** Several cost breakdowns in parallel (same cache keys as useCostBreakdown). */
export const useCostBreakdowns = (spec: TimeRangeSpec, key: string, list: CostFilters[]) =>
  useQueries({ queries: list.map((f) => ({ queryKey: ["cost", key, f], queryFn: () => api<CostBreakdown>(`cost/breakdown${qs({ ...rq(spec), ...f })}`), retry })) });
export const useCostBreakdown = (spec: TimeRangeSpec, key: string, f: CostFilters = {}) =>
  useQuery<CostBreakdown, ApiError>({
    queryKey: ["cost", key, f],
    queryFn: () => api(`cost/breakdown${qs({ ...rq(spec), ...f })}`),
    retry,
    placeholderData: keepPreviousData,
  });

export const useProjects = (periodDays = 7) =>
  useQuery<Paginated<Project>, ApiError>({ queryKey: ["projects", periodDays], queryFn: () => api(`projects${qs({ page_size: 100, period_days: periodDays })}`), retry });

export const useProject = (id: string, periodDays = 30) =>
  useQuery<Project, ApiError>({ queryKey: ["project", id, periodDays], queryFn: () => api(`projects/${id}${qs({ period_days: periodDays })}`), retry, enabled: !!id });

export const useObservedAgents = (spec: TimeRangeSpec, key: string) =>
  useQuery<Paginated<ObservedAgent>, ApiError>({ queryKey: ["agents", key], queryFn: () => api(`agents${qs(rq(spec))}`), retry });

export const useProjectAgents = (id: string, periodDays = 30) =>
  useQuery<Paginated<ObservedAgent>, ApiError>({ queryKey: ["project-agents", id, periodDays], queryFn: () => api(`projects/${id}/agents${qs({ period_days: periodDays })}`), retry, enabled: !!id });

export interface TraceFilters {
  project_id?: string;
  environment?: string;
  model_name?: string;
  success?: boolean;
  connector_id?: string;
  agent?: string;
  page?: number;
  page_size?: number;
}
export const useTraces = (spec: TimeRangeSpec, key: string, f: TraceFilters = {}, opts: { refetchInterval?: number | false } = {}) =>
  useQuery<Paginated<Span>, ApiError>({
    queryKey: ["traces", key, f],
    queryFn: () => api(`traces${qs({ ...rq(spec), ...f })}`),
    retry,
    placeholderData: keepPreviousData,
    refetchInterval: opts.refetchInterval,
  });

export const useTrace = (traceId: string | null) =>
  useQuery<Span, ApiError>({ queryKey: ["trace", traceId], queryFn: () => api(`traces/${traceId}`), retry, enabled: !!traceId });

export const useAlerts = (status: string) =>
  useQuery<Paginated<FiredAlert>, ApiError>({ queryKey: ["alerts", status], queryFn: () => api(`alerts${qs({ status, page_size: 200 })}`), retry, refetchInterval: 60_000 });

export const useAlertRules = () =>
  useQuery<Paginated<AlertRule>, ApiError>({ queryKey: ["alert-rules"], queryFn: () => api(`alert-rules${qs({ page_size: 200 })}`), retry });

/** Count of active alerts for the sidebar badge. */
export const useActiveAlertCount = () =>
  useQuery<number, ApiError>({
    queryKey: ["alerts", "active-count"],
    queryFn: async () => (await api<Paginated<FiredAlert>>(`alerts${qs({ status: "active", page_size: 1 })}`)).total,
    retry: false,
    refetchInterval: 60_000,
  });

// ─── Admin queries ──────────────────────────────────────────────────────

export const useConnectors = () =>
  useQuery<Connector[], ApiError>({ queryKey: ["connectors"], queryFn: () => admin("connectors"), retry });

export const useApiKeys = (projectId: string) =>
  useQuery<ApiKey[], ApiError>({ queryKey: ["api-keys", projectId], queryFn: () => admin(`projects/${projectId}/api-keys`), retry, enabled: !!projectId });

export const usePricing = () =>
  useQuery<ModelPricing[], ApiError>({ queryKey: ["pricing"], queryFn: () => admin("pricing/models"), retry });

// ─── Mutations ──────────────────────────────────────────────────────────

function useInvalidate() {
  const qc = useQueryClient();
  return (...keys: string[]) => keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

export function useAlertAction() {
  const inv = useInvalidate();
  return useMutation<unknown, ApiError, { id: string; action: "acknowledge" | "resolve" }>({
    mutationFn: ({ id, action }) => api(`alerts/${id}/${action}`, { method: "PATCH" }),
    onSuccess: () => inv("alerts"),
  });
}
export interface AlertRuleInput {
  name: string; metric: string; operator: AlertRule["operator"]; threshold: number; window_minutes: number;
  severity: Severity; notification_channels: string[]; project_id?: string | null;
}
export function useCreateAlertRule() {
  const inv = useInvalidate();
  return useMutation<AlertRule, ApiError, AlertRuleInput>({
    mutationFn: (body) => api("alert-rules", { method: "POST", body }),
    onSuccess: () => inv("alert-rules"),
  });
}
export function useDeleteAlertRule() {
  const inv = useInvalidate();
  return useMutation<null, ApiError, string>({
    mutationFn: (id) => api(`alert-rules/${id}`, { method: "DELETE" }),
    onSuccess: () => inv("alert-rules"),
  });
}

export interface ProjectInput {
  name: string; slug: string; description?: string | null; content_capture_mode: CaptureMode;
  monthly_budget_usd?: number | null; tags?: string[];
}
export function useCreateProject() {
  const inv = useInvalidate();
  return useMutation<Project, ApiError, ProjectInput>({
    mutationFn: (body) => admin("projects", { method: "POST", body }),
    onSuccess: () => inv("projects"),
  });
}
export function useUpdateProject(id: string) {
  const inv = useInvalidate();
  return useMutation<Project, ApiError, Partial<ProjectInput> & { is_active?: boolean }>({
    mutationFn: (body) => admin(`projects/${id}`, { method: "PATCH", body }),
    onSuccess: () => inv("projects", "project"),
  });
}

export function useCreateApiKey(projectId: string) {
  const inv = useInvalidate();
  return useMutation<ApiKeyCreated, ApiError, { name: string; scopes?: string[] }>({
    mutationFn: (body) => admin(`projects/${projectId}/api-keys`, { method: "POST", body }),
    onSuccess: () => inv("api-keys"),
  });
}
export function useRevokeApiKey() {
  const inv = useInvalidate();
  return useMutation<null, ApiError, string>({
    mutationFn: (id) => admin(`api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => inv("api-keys"),
  });
}

export interface ConnectorInput {
  name: string; provider: ConnectorProvider; project_id?: string | null;
  config: Record<string, unknown>; credentials: Record<string, string>;
  sync_interval_minutes: number; is_active?: boolean;
}
export function useCreateConnector() {
  const inv = useInvalidate();
  return useMutation<Connector, ApiError, ConnectorInput>({
    mutationFn: (body) => admin("connectors", { method: "POST", body }),
    onSuccess: () => inv("connectors"),
  });
}
export function useUpdateConnector() {
  const inv = useInvalidate();
  return useMutation<Connector, ApiError, { id: string; body: Partial<ConnectorInput> }>({
    mutationFn: ({ id, body }) => admin(`connectors/${id}`, { method: "PUT", body }),
    onSuccess: () => inv("connectors"),
  });
}
export function useDeleteConnector() {
  const inv = useInvalidate();
  return useMutation<null, ApiError, string>({
    mutationFn: (id) => admin(`connectors/${id}`, { method: "DELETE" }),
    onSuccess: () => inv("connectors"),
  });
}
export function useTestConnector() {
  return useMutation<ConnectorTestResult, ApiError, string>({ mutationFn: (id) => admin(`connectors/${id}/test`, { method: "POST" }) });
}
export function useSyncConnector() {
  const inv = useInvalidate();
  return useMutation<SyncResult, ApiError, string>({
    mutationFn: (id) => admin(`connectors/${id}/sync`, { method: "POST" }),
    onSuccess: () => inv("connectors", "traces", "overview", "cost"),
  });
}

export function useCreatePricing() {
  const inv = useInvalidate();
  return useMutation<ModelPricing, ApiError, Omit<ModelPricing, "id" | "is_active" | "effective_from" | "model_version"> & { model_version?: string | null }>({
    mutationFn: (body) => admin("pricing/models", { method: "POST", body }),
    onSuccess: () => inv("pricing"),
  });
}
export function useSeedPricing() {
  const inv = useInvalidate();
  return useMutation<unknown, ApiError, void>({ mutationFn: () => admin("pricing/models/seed", { method: "POST" }), onSuccess: () => inv("pricing") });
}
export function useDeactivatePricing() {
  const inv = useInvalidate();
  return useMutation<null, ApiError, string>({ mutationFn: (id) => admin(`pricing/models/${id}`, { method: "DELETE" }), onSuccess: () => inv("pricing") });
}

// ─── Clients ─────────────────────────────────────────────────────────────

/** Clients with spend, calls and project count for the last `periodDays` (analytics API). */
export const useClients = (periodDays = 30) =>
  useQuery<Paginated<Client>, ApiError>({ queryKey: ["clients", periodDays], queryFn: () => api(`clients${qs({ page_size: 100, period_days: periodDays })}`), retry });

export interface ClientInput { name: string; slug: string; client_type: ClientType; description?: string | null; monthly_budget_usd?: number | null }
/** Create a client (admin service). */
export function useCreateClient() {
  const qc = useQueryClient();
  return useMutation<Client, ApiError, ClientInput>({
    mutationFn: (body) => admin("clients", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}
/** Update a client's name, description, budget or active flag (admin service). */
export function useUpdateClient(id: string) {
  const qc = useQueryClient();
  return useMutation<Client, ApiError, Partial<Omit<ClientInput, "slug" | "client_type">> & { is_active?: boolean }>({
    mutationFn: (body) => admin(`clients/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}
