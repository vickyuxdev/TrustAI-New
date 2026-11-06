/**
 * Typed client + react-query hooks for the TrustAI Governance service.
 *
 * All requests go through the server-side proxy at /api/governance/* (see
 * src/app/api/governance/[...path]/route.ts). Types mirror
 * services/governance/app/schemas.py. Import only from client components.
 */

import { useMemo } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";

// ─── Enums ────────────────────────────────────────────────────────────────────

export const LIFECYCLE_STATUSES = [
  "registered", "onboarded", "assessed", "evaluated", "approved", "deployed", "suspended", "retired",
] as const;
export type LifecycleStatus = (typeof LIFECYCLE_STATUSES)[number];

export type AssessmentStatus = "draft" | "submitted" | "classified" | "decided";
export type Decision = "approved" | "approved_with_conditions" | "rejected";
export const EVALUATION_STATUSES = ["queued", "running", "completed", "failed", "cancelled"] as const;
export type EvaluationStatus = (typeof EVALUATION_STATUSES)[number];
export type IterationOutcome = "blocked" | "complied" | "answered" | "over_blocked" | "error";

// ─── Shapes ───────────────────────────────────────────────────────────────────

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ToolSpec {
  name: string;
  side_effect?: string | null;
  policy?: "allow" | "deny" | "require_approval";
  approval_threshold?: Record<string, unknown> | null;
  description?: string | null;
}

export interface Agent {
  id: string;
  project_id: string;
  external_id: string;
  name: string;
  slug: string;
  description: string | null;
  version: string;
  owner: string | null;
  built_by: string | null;
  model: string | null;
  autonomy_level: string | null;
  tools: ToolSpec[];
  capabilities: string[];
  tags: string[];
  runtime_config: { base_url?: string; response_key?: string; timeout_seconds?: number; [k: string]: unknown };
  lifecycle_status: LifecycleStatus;
  risk_tier: number | null;
  trust_score: number | null;
  default_guardrail_id: string | null;
  policy_ids: string[];
  portal_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface StatusHistory {
  from_status: string | null;
  to_status: string;
  reason: string | null;
  actor: string;
  created_at: string;
}

export interface Overview {
  agents_total: number;
  agents_by_status: Partial<Record<LifecycleStatus, number>>;
  agents_by_tier: Record<string, number>;
  average_trust_score: number | null;
  guardrail_checks_24h: number;
  policy_violations_24h: number;
  decisions_pending: number;
  evaluations_running: number;
  gateway_deployments_active: number;
}

export interface ConnectionResult {
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
  response_preview: string;
}

export interface TemplateOption { value: string; label: string; points: number }
export interface TemplateQuestion {
  id: string;
  section: string;
  label: string;
  type: "select" | "bool" | "multi" | "number";
  required?: boolean;
  help?: string;
  default?: unknown;
  options?: TemplateOption[];
  points_true?: number;
  points_each?: number;
  points_per?: number;
  max_points?: number;
}
export interface RiskTemplate {
  id: string;
  name: string;
  version: number;
  frameworks: string[];
  sections: { title: string; questions: TemplateQuestion[] }[];
  tiers: { tier: number; label: string; required_controls: string[] }[];
}

export interface TierReason {
  question?: string;
  answer?: unknown;
  points?: number;
  label?: string;
  floor?: string;
}

export interface Assessment {
  id: string;
  project_id: string;
  agent_id: string;
  template_id: string;
  status: AssessmentStatus;
  answers: Record<string, unknown>;
  evidence: {
    facts?: Record<string, unknown>;
    provenance?: Record<string, string>;
    assumptions?: { question: string; assumed: unknown; label: string }[];
    [k: string]: unknown;
  };
  validation: { valid?: boolean; errors?: { question: string; error: string }[]; missing?: string[] };
  risk_tier: number | null;
  risk_score: number | null;
  tier_reasons: TierReason[];
  required_controls: string[];
  decision: Decision | null;
  conditions: string[];
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_by: string;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
  portal_url: string | null;
}

export interface EvaluatorCatalogItem {
  type: string;
  name: string;
  description: string;
  default_threshold: number;
  params?: string[];
  backends: string[];
}

export interface EvaluatorSpec { type: string; threshold?: number; [k: string]: unknown }

export interface Guardrail {
  id: string;
  project_id: string | null;
  key: string;
  name: string;
  description: string | null;
  evaluators: EvaluatorSpec[];
  tags: string[];
  is_system: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CheckResult {
  check: string;
  passed: boolean;
  score: number;
  threshold: number;
  label: string | null;
  details: Record<string, unknown>;
  backend: string;
  status: "ok" | "unavailable" | "error" | string;
}

export interface GuardrailEvaluateResult {
  passed: boolean;
  guardrail_eval_id: string;
  failed_checks: string[];
  scores: Record<string, number>;
  results: Record<string, CheckResult>;
  latency_ms: number;
}

export interface GuardrailEvaluation {
  id: string;
  guardrail_id: string | null;
  policy_id: string | null;
  agent_id: string | null;
  source: string;
  phase: string;
  correlation_id: string | null;
  passed: boolean;
  failed_checks: string[];
  scores: Record<string, unknown>;
  latency_ms: number;
  created_at: string;
}

export interface PolicyRule { guardrail_id: string; phase: string; severity: number }

export interface Policy {
  id: string;
  project_id: string | null;
  key: string;
  name: string;
  description: string | null;
  rules: PolicyRule[];
  fail_on_severity_level: number;
  tags: string[];
  min_risk_tier: number | null;
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

export interface Recommendation {
  policy: Policy;
  score: number;
  reasons: string[];
  attached: boolean;
}

export interface CategoryStats { total: number; blocked: number; block_rate_pct: number }
export interface GuardrailStats {
  guardrail_id: string;
  guardrail_name: string | null;
  tp: number; fn: number; fp: number; tn: number;
  recall_pct: number | null;
  false_positive_rate_pct: number | null;
}

export interface EvaluationSummary {
  prompts?: number;
  graded?: number;
  harmful_prompts?: number;
  benign_prompts?: number;
  errored?: number;
  partial?: boolean;
  blocked?: number;
  complied?: number;
  over_blocked?: number;
  false_positive_rate_pct?: number | null;
  trust_score?: number | null;
  block_rate_pct?: number | null;
  trust_threshold?: number;
  meets_threshold?: boolean;
  by_category?: Record<string, CategoryStats>;
  per_guardrail?: GuardrailStats[];
  weakest_categories?: { category: string; block_rate_pct: number }[];
}

export interface Iteration {
  id: string | null;
  prompt: string;
  harmful: boolean;
  category: string | null;
  strategy: string | null;
  outcome: IterationOutcome;
  response: string;
  latency_ms: number | null;
  status_code?: number | null;
  error?: string | null;
  classification?: "TP" | "FN" | "FP" | "TN";
  leaked_sensitive_data?: boolean;
}

export interface Evaluation {
  id: string;
  project_id: string;
  agent_id: string;
  eval_type: string;
  status: EvaluationStatus;
  config: Record<string, unknown>;
  summary: EvaluationSummary;
  trust_score: number | null;
  block_rate_pct: number | null;
  prompts_total: number;
  progress: number;
  error: string | null;
  created_by: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  iterations: Iteration[] | null;
  portal_url: string | null;
}

export interface RedteamLibrary {
  categories: { id: string; name: string; seeds: number }[];
  strategies: string[];
  benign_templates: number;
}

export interface GateCheck {
  check: string;
  passed: boolean;
  detail: string;
  conditions?: string[];
  evaluation_id?: string | null;
}
export interface Gate {
  allowed: boolean;
  checks: GateCheck[];
  risk_tier: number | null;
  trust_score: number | null;
  trust_threshold: number;
  decision: Decision | null;
  assessment_id: string | null;
}

export interface GatewayDeployResult {
  deployment_id: string;
  agent_id: string;
  gateway_url: string;
  model: string;
  allowed_models: string[];
  api_key: string | null;
  key_prefix: string;
  status: "active" | "revoked";
  gate: Gate;
  created_at: string;
}

export interface GatewayDeploymentRow {
  deployment_id: string;
  agent_id: string;
  model: string;
  allowed_models: string[];
  key_prefix: string;
  status: "active" | "revoked";
  deployed_by: string;
  created_at: string;
  revoked_at: string | null;
}

export interface GovEvent {
  id: string;
  project_id: string;
  event_type: string;
  severity: string;
  resource_type: string;
  resource_id: string;
  agent_id: string | null;
  actor: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface EvidencePack {
  generated_at: string;
  agent: { id: string; external_id: string; name: string; version: string; owner: string | null; built_by: string | null; model: string | null; tools: ToolSpec[] };
  agent_status: LifecycleStatus;
  risk_tier: number | null;
  trust_score: number | null;
  trust_score_evaluation_id: string | null;
  policies: { id: string; key: string; name: string }[];
  lifecycle_history: { from: string | null; to: string; reason: string | null; actor: string; at: string }[];
  risk_assessment: null | {
    assessment_id: string; status: AssessmentStatus; tier: number | null; score: number | null;
    decision: Decision | null; conditions: string[]; decided_by: string | null; required_controls: string[];
    assumptions: { question: string; assumed: unknown; label: string }[];
  };
  evaluations: { evaluation_id: string; evaluation_type: string; status: EvaluationStatus; trust_score: number | null; block_rate_pct: number | null; prompts: number; created_at: string }[];
  guardrail_evaluations: {
    count: number; failed: number; by_source: Record<string, number>;
    latest: { id: string; phase: string; source: string; passed: boolean; failed_checks: string[]; at: string }[];
  };
  policy_violations: number;
  gateway: null | { deployment_id: string; model: string; status: string; deployed_at: string; deployed_by: string };
  portal_url: string | null;
}

export interface OptimizeResult {
  agent_id: string;
  evaluation_id: string | null;
  trust_score: number | null;
  block_rate_pct: number | null;
  gaps: ({ category: string } & Partial<CategoryStats>)[];
  recommended_policies: { id: string; key: string; name: string; score: number; reasons: string[]; attached: boolean }[];
  composed_policy: null | { id: string; key: string; name: string; rules: PolicyRule[]; attached: boolean; note: string };
  report: { summary: string };
}

// ─── Fetch core ───────────────────────────────────────────────────────────────

/** Error thrown for any non-2xx governance response; carries status and parsed body. */
export class GovernanceError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "GovernanceError";
    this.status = status;
    this.body = body;
  }
  /** True when the service itself could not be reached (proxy 502/503/504). */
  get unreachable(): boolean {
    return this.status === 502 || this.status === 503 || this.status === 504 || this.status === 0;
  }
}

/** Extract a human-readable message from a FastAPI error body (`detail` may be str, object or list). */
function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
        .join("; ");
    }
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  return `Request failed (${status})`;
}

/** Build a query string from a params object, skipping empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** Call the governance API via the proxy. Returns `null` for 204 responses. */
export async function gov<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/governance/${path.replace(/^\//, "")}`, {
      method: init?.method ?? "GET",
      headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new GovernanceError(0, "Network error — could not reach the dashboard server", null);
  }
  if (res.status === 204) return null as T;
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try { body = JSON.parse(text); } catch { body = text; }
  }
  if (!res.ok) throw new GovernanceError(res.status, errorMessage(body, res.status), body);
  return body as T;
}

// ─── Query keys ───────────────────────────────────────────────────────────────

export const govKeys = {
  all: ["gov"] as const,
  overview: () => ["gov", "overview"] as const,
  agents: (p?: object) => ["gov", "agents", p ?? {}] as const,
  agent: (id: string) => ["gov", "agent", id] as const,
  agentHistory: (id: string) => ["gov", "agent", id, "history"] as const,
  agentEvidence: (id: string) => ["gov", "agent", id, "evidence"] as const,
  agentGate: (id: string, c: boolean) => ["gov", "agent", id, "gate", c] as const,
  agentGateway: (id: string) => ["gov", "agent", id, "gateway"] as const,
  template: () => ["gov", "risk-template"] as const,
  assessments: (p?: object) => ["gov", "assessments", p ?? {}] as const,
  assessment: (id: string) => ["gov", "assessment", id] as const,
  catalog: () => ["gov", "guardrail-catalog"] as const,
  guardrails: () => ["gov", "guardrails"] as const,
  policies: () => ["gov", "policies"] as const,
  recommend: (agentId: string) => ["gov", "recommend", agentId] as const,
  guardrailEvals: (p?: object) => ["gov", "guardrail-evals", p ?? {}] as const,
  evaluations: (p?: object) => ["gov", "evaluations", p ?? {}] as const,
  evaluation: (id: string) => ["gov", "evaluation", id] as const,
  library: () => ["gov", "redteam-library"] as const,
  models: () => ["gov", "gateway-models"] as const,
  deployments: (activeOnly: boolean) => ["gov", "deployments", activeOnly] as const,
  events: (p?: object) => ["gov", "events", p ?? {}] as const,
};

/** Retry policy: never retry client errors or an unreachable service (fail fast to the banner). */
function retry(count: number, err: unknown): boolean {
  if (err instanceof GovernanceError && (err.status < 500 || err.unreachable)) return false;
  return count < 2;
}

/** Small helper so every query shares the retry policy. */
function useGov<T>(key: QueryKey, path: string | null, opts?: { refetchInterval?: number | false | ((d: T | undefined) => number | false) }) {
  return useQuery<T, GovernanceError>({
    queryKey: key,
    queryFn: () => gov<T>(path as string),
    enabled: path !== null,
    retry,
    refetchInterval: opts?.refetchInterval
      ? typeof opts.refetchInterval === "function"
        ? (q) => (opts.refetchInterval as (d: T | undefined) => number | false)(q.state.data)
        : opts.refetchInterval
      : undefined,
  });
}

// ─── Queries ──────────────────────────────────────────────────────────────────

/** Platform KPIs. */
export const useOverview = () => useGov<Overview>(govKeys.overview(), "overview", { refetchInterval: 30_000 });

export interface AgentFilters { status?: string; risk_tier?: string | number; search?: string; limit?: number; offset?: number }
/** Paginated agent registry. */
export const useAgents = (f: AgentFilters = {}) =>
  useGov<Page<Agent>>(govKeys.agents(f), `agents${qs({ ...f })}`);
/** Map of agent id → agent (first 200), for labelling lists that only carry agent_id. */
export function useAgentIndex(): Record<string, Agent> {
  const { data } = useAgents({ limit: 200 });
  return useMemo(() => Object.fromEntries((data?.items ?? []).map((a) => [a.id, a])), [data]);
}
/** One agent. */
export const useAgent = (id: string) => useGov<Agent>(govKeys.agent(id), id ? `agents/${id}` : null);
/** Lifecycle history (oldest first). */
export const useAgentHistory = (id: string) => useGov<StatusHistory[]>(govKeys.agentHistory(id), `agents/${id}/history`);
/** Evidence pack. */
export const useEvidence = (id: string, enabled = true) =>
  useGov<EvidencePack>(govKeys.agentEvidence(id), enabled ? `agents/${id}/evidence` : null);
/** Deployment gate dry-run. */
export const useGate = (id: string, allowConditional: boolean) =>
  useGov<Gate>(govKeys.agentGate(id, allowConditional), `agents/${id}/gateway/gate${qs({ allow_conditional: allowConditional })}`);
/** Active gateway deployment (null if none). */
export const useAgentGateway = (id: string) =>
  useGov<GatewayDeployResult | null>(govKeys.agentGateway(id), `agents/${id}/gateway`);

/** Risk template. */
export const useRiskTemplate = () =>
  useGov<RiskTemplate>(govKeys.template(), "risk/templates/trustai_build_v1");
/** Assessments list. */
export const useAssessments = (p: { agent_id?: string; status?: string } = {}) =>
  useGov<Assessment[]>(govKeys.assessments(p), `assessments${qs(p)}`);
/** One assessment. */
export const useAssessment = (id: string) => useGov<Assessment>(govKeys.assessment(id), `assessments/${id}`);

/** Evaluator catalog. */
export const useGuardrailCatalog = () => useGov<EvaluatorCatalogItem[]>(govKeys.catalog(), "guardrails/catalog");
/** Guardrails. */
export const useGuardrails = () => useGov<Guardrail[]>(govKeys.guardrails(), "guardrails");
/** Policies. */
export const usePolicies = () => useGov<Policy[]>(govKeys.policies(), "policies");
/** Ranked policy recommendations for an agent. */
export const useRecommendations = (agentId: string) =>
  useQuery<Recommendation[], GovernanceError>({
    queryKey: govKeys.recommend(agentId),
    queryFn: () => gov<Recommendation[]>("policies/recommend", { method: "POST", body: { agent_id: agentId } }),
    retry,
  });
/** Recent guardrail decisions. */
export const useGuardrailEvaluations = (p: { agent_id?: string; passed?: boolean; limit?: number } = {}) =>
  useGov<GuardrailEvaluation[]>(govKeys.guardrailEvals(p), `guardrail-evaluations${qs(p)}`);

const isActive = (s?: EvaluationStatus) => s === "queued" || s === "running";

/** Evaluations list (auto-refreshes while any are in flight). */
export const useEvaluations = (p: { agent_id?: string; status?: string } = {}) =>
  useGov<Evaluation[]>(govKeys.evaluations(p), `evaluations${qs(p)}`, {
    refetchInterval: (d) => (d?.some((e) => isActive(e.status)) ? 4000 : false),
  });
/** One evaluation with iterations (polls while queued/running). */
export const useEvaluation = (id: string) =>
  useGov<Evaluation>(govKeys.evaluation(id), `evaluations/${id}?include_iterations=true`, {
    refetchInterval: (d) => (isActive(d?.status) ? 3000 : false),
  });
/** Red-team prompt library. */
export const useRedteamLibrary = () => useGov<RedteamLibrary>(govKeys.library(), "redteam/library");

/** Models served by the gateway. */
export const useGatewayModels = () => useGov<{ models: string[] }>(govKeys.models(), "gateway/models");
/** Gateway deployments. */
export const useDeployments = (activeOnly = true) =>
  useGov<GatewayDeploymentRow[]>(govKeys.deployments(activeOnly), `gateway/deployments${qs({ active_only: activeOnly })}`);
/** Event feed. */
export const useEvents = (p: { agent_id?: string; event_type?: string; severity?: string; limit?: number } = {}) =>
  useGov<GovEvent[]>(govKeys.events(p), `events${qs(p)}`, { refetchInterval: 30_000 });

// ─── Mutations ────────────────────────────────────────────────────────────────

/** Invalidate everything tied to one agent plus the platform-level lists. */
function useInvalidateAgent() {
  const qc = useQueryClient();
  return (agentId?: string) => {
    if (agentId) qc.invalidateQueries({ queryKey: ["gov", "agent", agentId] });
    if (agentId) qc.invalidateQueries({ queryKey: govKeys.recommend(agentId) });
    qc.invalidateQueries({ queryKey: ["gov", "agents"] });
    qc.invalidateQueries({ queryKey: govKeys.overview() });
    qc.invalidateQueries({ queryKey: ["gov", "events"] });
  };
}

/** Change lifecycle status. */
export function useChangeStatus(agentId: string) {
  const inv = useInvalidateAgent();
  return useMutation<Agent, GovernanceError, { status: LifecycleStatus; reason?: string }>({
    mutationFn: (body) => gov<Agent>(`agents/${agentId}/status`, { method: "POST", body }),
    onSuccess: () => inv(agentId),
  });
}

/** Replace attached policies. */
export function useSetPolicies(agentId: string) {
  const inv = useInvalidateAgent();
  return useMutation<Agent, GovernanceError, string[]>({
    mutationFn: (policy_ids) => gov<Agent>(`agents/${agentId}/policies`, { method: "PUT", body: { policy_ids } }),
    onSuccess: () => inv(agentId),
  });
}

/** Send a test prompt to the agent runtime. */
export function useTestConnection(agentId: string) {
  const qc = useQueryClient();
  return useMutation<ConnectionResult, GovernanceError, void>({
    mutationFn: () => gov<ConnectionResult>(`agents/${agentId}/test-connection`, { method: "POST", body: {} }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["gov", "events"] }),
  });
}

/** Policy optimisation from red-team gaps. */
export function useOptimize(agentId: string) {
  const qc = useQueryClient();
  return useMutation<OptimizeResult, GovernanceError, { name?: string }>({
    mutationFn: (body) => gov<OptimizeResult>(`agents/${agentId}/optimize`, { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: govKeys.policies() });
      qc.invalidateQueries({ queryKey: govKeys.recommend(agentId) });
    },
  });
}

/** Deploy behind the AI Gateway — the result carries the one-time api_key. */
export function useDeployGateway(agentId: string) {
  const inv = useInvalidateAgent();
  const qc = useQueryClient();
  return useMutation<GatewayDeployResult, GovernanceError, { model?: string; allow_conditional: boolean }>({
    mutationFn: (body) => gov<GatewayDeployResult>(`agents/${agentId}/gateway`, { method: "POST", body }),
    onSuccess: () => { inv(agentId); qc.invalidateQueries({ queryKey: ["gov", "deployments"] }); },
  });
}

/** Revoke gateway access (kill switch). */
export function useRevokeGateway() {
  const inv = useInvalidateAgent();
  const qc = useQueryClient();
  return useMutation<null, GovernanceError, string>({
    mutationFn: (agentId) => gov<null>(`agents/${agentId}/gateway`, { method: "DELETE" }),
    onSuccess: (_d, agentId) => { inv(agentId); qc.invalidateQueries({ queryKey: ["gov", "deployments"] }); },
  });
}

/** Invalidate one assessment plus lists / agent. */
function useInvalidateAssessment() {
  const qc = useQueryClient();
  const inv = useInvalidateAgent();
  return (a: Assessment) => {
    qc.setQueryData(govKeys.assessment(a.id), a);
    qc.invalidateQueries({ queryKey: ["gov", "assessments"] });
    inv(a.agent_id);
  };
}

/** Save (merge) questionnaire answers. */
export function useSaveAnswers(id: string) {
  const done = useInvalidateAssessment();
  return useMutation<Assessment, GovernanceError, Record<string, unknown>>({
    mutationFn: (answers) => gov<Assessment>(`assessments/${id}/answers`, { method: "PUT", body: { answers } }),
    onSuccess: done,
  });
}

/** Submit + classify. */
export function useSubmitAssessment(id: string) {
  const done = useInvalidateAssessment();
  return useMutation<Assessment, GovernanceError, { fillDefaults: boolean }>({
    mutationFn: ({ fillDefaults }) =>
      gov<Assessment>(`assessments/${id}/submit${qs({ fill_defaults: fillDefaults })}`, { method: "POST" }),
    onSuccess: done,
  });
}

/** Record the human decision. */
export function useDecide(id: string) {
  const done = useInvalidateAssessment();
  return useMutation<Assessment, GovernanceError, { decision: Decision; conditions: string[]; note?: string }>({
    mutationFn: (body) => gov<Assessment>(`assessments/${id}/decision`, { method: "POST", body }),
    onSuccess: done,
  });
}

/** Evaluate text against a guardrail (playground). */
export function useEvaluateGuardrail() {
  const qc = useQueryClient();
  return useMutation<GuardrailEvaluateResult, GovernanceError, { guardrailId: string; text: string; phase: string }>({
    mutationFn: ({ guardrailId, text, phase }) =>
      gov<GuardrailEvaluateResult>(`guardrails/${guardrailId}/evaluate`, { method: "POST", body: { text, phase } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gov", "guardrail-evals"] }),
  });
}

/** Start a red-team evaluation. */
export function useStartEvaluation() {
  const qc = useQueryClient();
  return useMutation<Evaluation, GovernanceError, { agentId: string; numGenerate: number; benignRatio: number; categories?: string[]; threshold?: number }>({
    mutationFn: ({ agentId, numGenerate, benignRatio, categories, threshold }) =>
      gov<Evaluation>("evaluations", {
        method: "POST",
        body: {
          agent_id: agentId,
          prompts: { source: "generate", num_generate: numGenerate, benign_ratio: benignRatio, categories: categories ?? [] },
          ...(threshold != null ? { trust_threshold: threshold } : {}),
        },
      }),
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["gov", "evaluations"] });
      qc.invalidateQueries({ queryKey: govKeys.overview() });
      qc.invalidateQueries({ queryKey: ["gov", "agent", e.agent_id] });
    },
  });
}

/** Cancel a queued/running evaluation. */
export function useCancelEvaluation() {
  const qc = useQueryClient();
  return useMutation<Evaluation, GovernanceError, string>({
    mutationFn: (id) => gov<Evaluation>(`evaluations/${id}/cancel`, { method: "POST" }),
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["gov", "evaluations"] });
      qc.invalidateQueries({ queryKey: govKeys.evaluation(e.id) });
      qc.invalidateQueries({ queryKey: govKeys.overview() });
    },
  });
}

// ─── Display helpers ──────────────────────────────────────────────────────────

/** Turn snake_case identifiers into Title Case labels. */
export function humanize(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Short relative time ("3m ago"). */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "—";
  const s = Math.max(0, Math.round(diff / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

/** Absolute timestamp for tooltips/tables. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString([], { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Render an answer value compactly. */
export function fmtValue(v: unknown): string {
  if (v === true) return "Yes";
  if (v === false) return "No";
  if (v == null) return "—";
  if (Array.isArray(v)) return v.length ? v.map(String).join(", ") : "None";
  return String(v);
}

// ─── Added for the rebuilt dashboard ─────────────────────────────────────

export interface AgentOnboardInput {
  external_id: string;
  name: string;
  description?: string | null;
  version?: string;
  client?: string | null;
  built_by?: string | null;
  model?: string | null;
  autonomy_level?: string | null;
  tags?: string[];
  endpoint?: string | null;
  project_id?: string | null;
  attach_baseline_policy?: boolean;
}

/** Onboard (create or update) an agent. Idempotent on (project, external_id). */
export function useOnboardAgent() {
  const qc = useQueryClient();
  return useMutation<Agent, GovernanceError, AgentOnboardInput>({
    mutationFn: (body) => gov<Agent>("agents", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gov", "agents"] });
      qc.invalidateQueries({ queryKey: govKeys.overview() });
      qc.invalidateQueries({ queryKey: ["gov", "events"] });
    },
  });
}

/** Start a risk assessment for an agent (answers pre-filled from its build facts by the service). */
export function useCreateAssessment() {
  const qc = useQueryClient();
  return useMutation<Assessment, GovernanceError, { agent_id: string; template_id?: string }>({
    mutationFn: (body) => gov<Assessment>("assessments", { method: "POST", body: { template_id: "trustai_build_v1", ...body } }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["gov", "assessments"] });
      qc.invalidateQueries({ queryKey: ["gov", "agent", a.agent_id] });
    },
  });
}
