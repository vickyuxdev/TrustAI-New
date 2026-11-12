"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Bot, Check, ChevronDown, ClipboardCheck, Download, Network, Plug, Plus, Power, ShieldCheck, Sparkles, Swords, Wrench, X } from "lucide-react";
import { CheckRing, MiniBars, RangeTrend, Sparkline } from "@/components/charts";
import { AssessmentBadge, DecisionBadge, EvalBadge, LifecycleBadge, LIFE_LABEL, TierBadge, TrustScore } from "@/components/gov";
import { StartEvalModal } from "@/components/GovModals";
import { Card, CardHeader, CopyButton, Empty, ErrorState, Kpi, Modal, Pill, Skel, SkelRows, Tabs, errMsg, useToast } from "@/components/ui";
import {
  useAgent, useAgentGateway, useAgentHistory, useAssessments, useChangeStatus, useCreateAssessment, useDeployGateway, useEvaluations, useEvents,
  useEvidence, useGate, useGatewayModels, useOptimize, usePolicies, useRecommendations, useRevokeGateway, useSetPolicies, useTestConnection,
  LIFECYCLE_STATUSES, type Agent, type GatewayDeployResult, type LifecycleStatus, type OptimizeResult,
} from "@/lib/governance";
import { ago, humanize, ms, when } from "@/lib/format";

const TRANSITIONS: Record<LifecycleStatus, LifecycleStatus[]> = {
  registered: ["onboarded", "retired"],
  onboarded: ["assessed", "evaluated", "suspended", "retired"],
  assessed: ["evaluated", "onboarded", "suspended", "retired"],
  evaluated: ["approved", "assessed", "onboarded", "suspended", "retired"],
  approved: ["evaluated", "suspended", "retired"],
  deployed: ["evaluated", "suspended", "retired"],
  suspended: ["onboarded", "evaluated", "retired"],
  retired: [],
};
type TabId = "overview" | "risk" | "policies" | "redteam" | "gateway" | "evidence";

const CHECK_LABEL: Record<string, string> = {
  lifecycle_status: "Approved for release", risk_decision: "Risk decision recorded", trust_score: "Trust score at or above 95", policies_attached: "Policies attached",
};
const TIER_COL = ["var(--g1)", "var(--g2)", "var(--g3)", "var(--danger)"];
const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const sentence = (v: string) => { const t = v.replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase(); };
const fin = (e: { finished_at?: string | null; created_at: string }) => +new Date(e.finished_at ?? e.created_at);

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const agent = useAgent(id);
  const a = agent.data;
  const [tab, setTab] = useState<TabId>("overview");
  const assessments = useAssessments({ agent_id: id });
  const evals = useEvaluations({ agent_id: id });
  const history = useAgentHistory(id);

  if (agent.isError) return <Card><ErrorState error={agent.error} onRetry={() => agent.refetch()} /></Card>;

  // Date each lifecycle stage was reached, from the status history.
  const reached: Record<string, string> = {};
  (history.data ?? []).forEach((h) => { reached[h.to_status] = h.created_at; });
  const path = LIFECYCLE_STATUSES.filter((s) => s !== "suspended" && s !== "retired");
  const idx = a ? path.indexOf(a.lifecycle_status as (typeof path)[number]) : -1;
  const off = a && (a.lifecycle_status === "suspended" || a.lifecycle_status === "retired");

  return (
    <>
      <Link href="/governance/agents" className="ad-back"><ArrowLeft className="ic" aria-hidden />Agent registry</Link>
      <section className="card ad-head">
        <header className="pd-hero">
          <span className="pd-icon" aria-hidden><Bot className="ic" /></span>
          <div className="pd-title">
            <div className="pd-name">
              <h1>{a ? a.name : <Skel w={220} h={24} />}</h1>
              {a && <LifecycleBadge status={a.lifecycle_status} />}
              {a && <TierBadge tier={a.risk_tier} />}
            </div>
            <p>{a?.description ?? " "}</p>
            <ul className="pd-meta">
              <li><span>Agent ID</span><b className="mono">{a?.external_id ?? "—"}</b>{a && <CopyButton text={a.external_id} label="Copy" />}</li>
              <li><span>Version</span><b>{a ? `v${a.version}` : "—"}</b></li>
              <li><span>Model</span><b>{a?.model ?? "Not set"}</b></li>
              <li><span>Owner</span><b>{a?.owner ?? "—"}</b></li>
              <li><span>Built by</span><b>{a?.built_by ?? "—"}</b></li>
            </ul>
          </div>
          <div className="pd-actions">{a && <HeaderActions agent={a} />}</div>
        </header>
        <ol className={`ad-steps${off ? " off" : ""}`} aria-label="Lifecycle">
          {path.map((s, i) => {
            const state = off ? (reached[s] ? "done" : "") : idx > i ? "done" : idx === i ? "cur" : "";
            return (
              <li key={s} className={state}>
                <span className="dot" aria-hidden>{state === "done" || (state === "cur" && i === path.length - 1) ? <Check className="ic" /> : i + 1}</span>
                <span className="lb"><b>{LIFE_LABEL[s]}</b><small>{reached[s] ? dayFmt.format(new Date(reached[s])) : state === "cur" ? "Now" : "—"}</small></span>
              </li>
            );
          })}
          {off && a && <li className="bad"><span className="dot" aria-hidden><X className="ic" /></span><span className="lb"><b>{LIFE_LABEL[a.lifecycle_status]}</b><small>{reached[a.lifecycle_status] ? dayFmt.format(new Date(reached[a.lifecycle_status])) : "Now"}</small></span></li>}
        </ol>
      </section>

      <div className="ad-tabs">
        <Tabs label="Agent sections" value={tab} onChange={setTab} tabs={[
          { id: "overview", label: "Overview" },
          { id: "risk", label: "Risk assessment", count: assessments.data?.length ?? null },
          { id: "policies", label: "Policies", count: a?.policy_ids.length ?? null },
          { id: "redteam", label: "Red-team", count: evals.data?.length ?? null },
          { id: "gateway", label: "Gateway" },
          { id: "evidence", label: "Evidence & history" },
        ]} />
      </div>

      {!a ? <Card><SkelRows rows={6} /></Card> : tab === "overview" ? <OverviewTab agent={a} onTab={setTab} /> : (
        <Card><div style={{ padding: 18 }}>
          {tab === "risk" ? <RiskTab agent={a} /> : tab === "policies" ? <PoliciesTab agent={a} />
            : tab === "redteam" ? <RedteamTab agent={a} /> : tab === "gateway" ? <GatewayTab agent={a} /> : <EvidenceTab agent={a} />}
        </div></Card>
      )}
    </>
  );
}

function HeaderActions({ agent }: { agent: Agent }) {
  const test = useTestConnection(agent.id);
  const change = useChangeStatus(agent.id);
  const toast = useToast();
  const [menu, setMenu] = useState(false);
  const [target, setTarget] = useState<LifecycleStatus | null>(null);
  const [reason, setReason] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [menu]);
  const next = TRANSITIONS[agent.lifecycle_status] ?? [];
  const hasEndpoint = Boolean(agent.runtime_config?.base_url);

  const runTest = () => test.mutate(undefined, {
    onSuccess: (r) => toast(r.ok ? `Agent answered in ${ms(r.latency_ms)}` : `Agent didn't answer: ${r.error ?? `HTTP ${r.status_code}`}`, !r.ok),
    onError: (e) => toast(errMsg(e), true),
  });
  const confirm = () => target && change.mutate({ status: target, reason: reason || undefined }, {
    onSuccess: () => { toast(`Moved to ${LIFE_LABEL[target]}`); setTarget(null); setReason(""); },
    onError: (e) => toast(errMsg(e), true),
  });

  return (
    <>
      <button type="button" className={`btn${test.isPending ? " spin" : ""}`} disabled={!hasEndpoint || test.isPending} title={hasEndpoint ? "Send a test prompt" : "Add a chat endpoint to test"} onClick={runTest}><Plug className="ic" aria-hidden />Test connection</button>
      <div style={{ position: "relative" }} ref={ref}>
        <button type="button" className="btn btn-primary" aria-haspopup="menu" aria-expanded={menu} disabled={!next.length} onClick={() => setMenu((m) => !m)}>Move stage<ChevronDown className="ic" aria-hidden /></button>
        {menu && (
          <div className="menu" role="menu" style={{ right: 0, top: 40 }}>
            {next.map((s) => (
              <button key={s} type="button" role="menuitem" onClick={() => { setMenu(false); setTarget(s); }}>
                <span>{LIFE_LABEL[s]}</span>{(s === "suspended" || s === "retired") && <span className="tag bad">Blocks traffic</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      <Modal open={!!target} onClose={() => setTarget(null)} title={target ? `Move to ${LIFE_LABEL[target]}?` : ""}
        sub={target === "retired" ? "Retired agents can't be brought back." : target === "suspended" ? "Gateway access stops immediately." : "The change is recorded in the audit trail."}
        footer={<><button type="button" className="btn" onClick={() => setTarget(null)}>Cancel</button>
          <button type="button" className={`btn ${target === "retired" || target === "suspended" ? "btn-danger" : "btn-primary"}`} disabled={change.isPending} onClick={confirm}>{change.isPending ? "Saving…" : "Confirm"}</button></>}>
        <div className="field"><label htmlFor="st-reason">Reason (optional)</label><textarea id="st-reason" className="textarea" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this changing?" /></div>
      </Modal>
    </>
  );
}

function OverviewTab({ agent: a, onTab }: { agent: Agent; onTab: (t: TabId) => void }) {
  const history = useAgentHistory(a.id);
  const events = useEvents({ agent_id: a.id, limit: 12 });
  const evals = useEvaluations({ agent_id: a.id });
  const assessments = useAssessments({ agent_id: a.id });
  const gate = useGate(a.id, true);
  const g = gate.data;

  const runs = (evals.data ?? []).filter((e) => e.status === "completed" && e.trust_score != null).sort((x, y) => fin(x) - fin(y));
  const last = runs[runs.length - 1], prev = runs[runs.length - 2];
  const decided = (assessments.data ?? []).filter((x) => x.decided_at).sort((x, y) => +new Date(y.decided_at!) - +new Date(x.decided_at!))[0];
  const cats = last ? Object.entries(last.summary.by_category ?? {}).map(([c, v]) => ({ c, rate: v.total ? (v.blocked / v.total) * 100 : 0, ...v })).sort((x, y) => x.rate - y.rate) : [];
  const passedChecks = g?.checks.filter((c) => c.passed).length ?? 0;
  const gated = a.tools.filter((t) => t.policy === "require_approval" || t.policy === "deny").length;

  // One activity feed: lifecycle moves and governance events, newest first.
  const feed = [
    ...(history.data ?? []).map((h, i) => ({ key: "h" + i, at: h.created_at, title: h.from_status ? `${LIFE_LABEL[h.from_status as LifecycleStatus] ?? h.from_status} → ${LIFE_LABEL[h.to_status as LifecycleStatus] ?? h.to_status}` : `Registered`, sub: `${h.actor}${h.reason ? ` · ${h.reason}` : ""}`, tone: "stage" })),
    ...(events.data ?? []).filter((e) => e.event_type !== "agent.status_changed").map((e) => ({ key: e.id, at: e.created_at, title: humanize(e.event_type.replace(/\./g, " ")), sub: e.actor, tone: ["high", "critical", "error"].includes(e.severity) ? "bad" : ["medium", "warning"].includes(e.severity) ? "wait" : "" })),
  ].sort((x, y) => +new Date(y.at) - +new Date(x.at)).slice(0, 4);

  return (
    <>
      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Agent figures">
        <Kpi icon={ShieldCheck} label="Trust score" value={a.trust_score != null ? <span style={{ color: a.trust_score < 95 ? "var(--danger)" : undefined }}>{a.trust_score.toFixed(1)}</span> : "—"}
          vis={runs.length > 1 ? <Sparkline values={runs.slice(-10).map((r) => r.trust_score as number)} width={88} height={30} color={(a.trust_score ?? 0) >= 95 ? "var(--accent)" : "var(--danger)"} /> : undefined}
          foot={last && prev ? <span><b className={(last.trust_score as number) >= (prev.trust_score as number) ? "kpi-up" : "kpi-down"}>{(last.trust_score as number) >= (prev.trust_score as number) ? "+" : "−"}{Math.abs((last.trust_score as number) - (prev.trust_score as number)).toFixed(1)}</b> vs previous run · release bar 95</span> : "Release bar is 95"} />
        <Kpi icon={ClipboardCheck} label="Risk tier" value={a.risk_tier ? <>Tier {a.risk_tier}<small className="kpi-of"> {["Minimal", "Limited", "High", "Critical"][a.risk_tier - 1]}</small></> : "Not assessed"}
          vis={<span className="ad-tier" aria-hidden>{TIER_COL.map((c, i) => <i key={i} style={{ background: a.risk_tier && i < a.risk_tier ? c : undefined }} />)}</span>}
          foot={decided ? `${sentence(decided.decision ?? "")} by ${decided.decided_by?.split("@")[0]} · ${dayFmt.format(new Date(decided.decided_at!))}` : "No risk decision yet"} />
        <Kpi icon={Swords} label="Red-team runs" value={String(runs.length)}
          vis={runs.length ? <MiniBars values={runs.slice(-10).map((r) => r.block_rate_pct ?? 0)} width={72} height={30} /> : undefined}
          foot={last ? `Latest blocked ${(last.block_rate_pct ?? 0).toFixed(1)}% of ${last.prompts_total} attacks` : "No runs yet"} />
        <Kpi icon={g?.allowed ? ShieldCheck : X} label="Release gate" tone={g && !g.allowed ? "bad" : undefined}
          value={!g ? "—" : g.allowed ? "Open" : <span style={{ color: "var(--danger)" }}>Blocked</span>}
          vis={g ? <CheckRing ok={g.allowed} size={30} /> : undefined}
          foot={g ? `${passedChecks} of ${g.checks.length} checks passed` : "Checking…"} />
      </section>

      <div className="ad-r1">
        <Card labelledBy="t-ts">
          <CardHeader id="t-ts" title="Trust score by red-team run" action={<button type="button" className="link" onClick={() => onTab("redteam")}>All runs<ArrowRight className="ic" aria-hidden /></button>} />
          <div className="ad-ts">
            <div className="ad-ts-chart">
              {evals.isLoading ? <Skel h={220} /> : runs.length < 2 ? <Empty icon={Swords} title="Not enough runs yet" /> : (
                <RangeTrend single name="Trust score" ariaLabel="Trust score per red-team run" labels={runs.map((r) => dayFmt.format(new Date(fin(r))))}
                  longs={runs.map((r) => `Run on ${when(r.finished_at ?? r.created_at)}`)} avg={runs.map((r) => r.trust_score as number)}
                  refValue={95} refLabel="Release bar 95" yMin={Math.min(60, Math.floor(Math.min(...runs.map((r) => r.trust_score as number)) / 10) * 10)} yMax={100} fmt={(v) => v.toFixed(1)}
                  extra={runs.map((r) => [{ name: "Attacks blocked", value: `${(r.block_rate_pct ?? 0).toFixed(1)}%` }])} />
              )}
            </div>
            <div className="ad-ts-cats">
              <div className="gv-rank-h"><span>Latest run · by attack type</span><span>Blocked</span></div>
              {!cats.length ? <p className="small muted">No completed run.</p> : (
                <div className="ad-cats">
                  {cats.map((c) => (
                    <div key={c.c} className="ad-cat" title={`${c.blocked} of ${c.total} blocked`}>
                      <span className="n">{humanize(c.c)}</span>
                      <span className="gv-bb"><i style={{ width: `${c.rate}%` }} />{c.rate < 95 && <em style={{ left: `${c.rate}%`, width: `${95 - c.rate}%` }} />}</span>
                      <b className="num">{c.rate.toFixed(0)}%</b>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Card>

        <Card labelledBy="t-gate">
          <CardHeader id="t-gate" title="Release gate" action={<button type="button" className="link" onClick={() => onTab("gateway")}>Gateway<ArrowRight className="ic" aria-hidden /></button>} />
          <div className="ad-gate">
            {gate.isLoading ? <SkelRows rows={4} /> : !g ? <p className="small muted">Gate status unavailable.</p> : (
              <>
                <div className={`ad-verdict${g.allowed ? "" : " bad"}`}>
                  {g.allowed ? <ShieldCheck className="ic" aria-hidden /> : <X className="ic" aria-hidden />}
                  <div><b>{g.allowed ? "Cleared to serve traffic" : "Not cleared for release"}</b><small>{g.allowed ? "Every check below passes." : `${g.checks.length - passedChecks} check${g.checks.length - passedChecks === 1 ? "" : "s"} still failing.`}</small></div>
                </div>
                <ul className="ad-checks">
                  {g.checks.map((c) => (
                    <li key={c.check} className={c.passed ? "ok" : "no"}>
                      <span className="ck" aria-label={c.passed ? "Passed" : "Failed"}>{c.passed ? <Check className="ic" /> : <X className="ic" />}</span>
                      <div><b>{CHECK_LABEL[c.check] ?? humanize(c.check)}</b><small>{c.detail}</small>
                        {!!c.conditions?.length && <small className="cond">Conditions: {c.conditions.join("; ")}</small>}</div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </Card>
      </div>

      <div className="ad-r2">
        <Card labelledBy="t-tools">
          <CardHeader id="t-tools" title="Tools & permissions" sub={`${a.tools.length} tools · ${gated} need a person or are blocked`} />
          {!a.tools.length ? <div className="ad-pad"><p className="small muted">This agent declares no tools.</p></div> : (
            <ul className="ad-tools">
              {a.tools.map((t) => (
                <li key={t.name}>
                  <span className={`ad-se ${t.side_effect === "write" || t.side_effect === "external" ? "w" : ""}`} aria-hidden><Wrench className="ic" /></span>
                  <div><b className="mono">{t.name}</b><small>{t.description ?? `${t.side_effect ? humanize(t.side_effect) : "No"} access`}</small></div>
                  <Pill tone={t.policy === "deny" ? "danger" : t.policy === "require_approval" ? "wait" : "accent"} dot>{t.policy === "require_approval" ? "Needs approval" : humanize(t.policy ?? "allow")}</Pill>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card labelledBy="t-prof">
          <CardHeader id="t-prof" title="Configuration" />
          <dl className="ad-kv">
            <div><dt>Autonomy</dt><dd>{a.autonomy_level ? humanize(a.autonomy_level) : "Not set"}</dd></div>
            <div><dt>Capabilities</dt><dd>{a.capabilities.length ? a.capabilities.map(humanize).join(", ") : "—"}</dd></div>
            <div><dt>Policies</dt><dd>{a.policy_ids.length} attached <button type="button" className="ad-lnk" onClick={() => onTab("policies")}>Manage</button></dd></div>
            <div><dt>Endpoint</dt><dd className="mono ellipsis" title={a.runtime_config?.base_url ?? ""}>{a.runtime_config?.base_url ?? <span className="muted">Not configured</span>}</dd></div>
            <div><dt>Tags</dt><dd className="row" style={{ flexWrap: "wrap", gap: 4 }}>{a.tags.length ? a.tags.map((t) => <span key={t} className="tag">{t}</span>) : "—"}</dd></div>
            <div><dt>Registered</dt><dd>{when(a.created_at)}</dd></div>
          </dl>
        </Card>

        <Card labelledBy="t-act">
          <CardHeader id="t-act" title="Activity" action={<button type="button" className="link" onClick={() => onTab("evidence")}>Full history<ArrowRight className="ic" aria-hidden /></button>} />
          {history.isLoading ? <div className="ad-pad"><SkelRows rows={4} /></div> : !feed.length ? <div className="ad-pad"><p className="small muted">No activity yet.</p></div> : (
            <ol className="ad-feed">
              {feed.map((f) => (
                <li key={f.key} className={f.tone}>
                  <span className="pt" aria-hidden />
                  <div><b>{f.title}</b><small>{f.sub}</small></div>
                  <time dateTime={f.at}>{ago(f.at)}</time>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </>
  );
}

function RiskTab({ agent: a }: { agent: Agent }) {
  const list = useAssessments({ agent_id: a.id });
  const create = useCreateAssessment();
  const router = useRouter();
  const toast = useToast();
  const items = list.data ?? [];
  const open = items.find((x) => x.status === "draft" || x.status === "submitted");
  const start = () => create.mutate({ agent_id: a.id }, { onSuccess: (x) => router.push(`/governance/risk/${x.id}`), onError: (e) => toast(errMsg(e), true) });
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="small muted" style={{ margin: 0 }}>The questionnaire is pre-filled from the agent&apos;s build facts. Submitting classifies it into a risk tier; a person then approves or rejects.</p>
        {open ? <Link href={`/governance/risk/${open.id}`} className="btn btn-primary"><ClipboardCheck className="ic" aria-hidden />Continue draft</Link>
          : <button type="button" className="btn btn-primary" disabled={create.isPending} onClick={start}><Plus className="ic" aria-hidden />{create.isPending ? "Starting…" : "Start assessment"}</button>}
      </div>
      {list.isError ? <ErrorState error={list.error} compact /> : list.isLoading ? <SkelRows rows={3} /> : !items.length ? (
        <Empty icon={ClipboardCheck} title="Not assessed yet">Start an assessment to give this agent a risk tier.</Empty>
      ) : (
        <div className="scroll-x"><table>
          <thead><tr><th>Started</th><th>Status</th><th>Tier</th><th className="r">Score</th><th>Decision</th><th>Decided by</th><th className="r">Required controls</th></tr></thead>
          <tbody>{items.map((x) => (
            <tr key={x.id} className="clickable" onClick={() => router.push(`/governance/risk/${x.id}`)}>
              <td className="strong">{when(x.created_at)}</td>
              <td><AssessmentBadge status={x.status} /></td>
              <td><TierBadge tier={x.risk_tier} /></td>
              <td className="r num">{x.risk_score ?? "—"}</td>
              <td>{x.status === "decided" || x.status === "classified" ? <DecisionBadge decision={x.decision} /> : <span className="muted">—</span>}</td>
              <td className="muted">{x.decided_by ?? "—"}</td>
              <td className="r">{x.required_controls.length}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}

function PoliciesTab({ agent: a }: { agent: Agent }) {
  const policies = usePolicies();
  const recs = useRecommendations(a.id);
  const setPolicies = useSetPolicies(a.id);
  const optimize = useOptimize(a.id);
  const toast = useToast();
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const byId = Object.fromEntries((policies.data ?? []).map((p) => [p.id, p]));
  const attached = a.policy_ids.map((pid) => byId[pid]).filter(Boolean);
  const save = (ids: string[], msg: string) => setPolicies.mutate(ids, { onSuccess: () => toast(msg), onError: (e) => toast(errMsg(e), true) });

  return (
    <div className="split-r" style={{ alignItems: "start" }}>
      <section>
        <h3 className="card-t" style={{ marginBottom: 6 }}>Attached policies</h3>
        {policies.isLoading ? <SkelRows rows={3} /> : !attached.length ? <Empty icon={ShieldCheck} title="No policies attached">Attach a recommended policy so guardrails run on this agent&apos;s traffic.</Empty> : (
          <ul className="list">{attached.map((p) => (
            <li key={p.id}>
              <div style={{ minWidth: 0 }}><b>{p.name}</b><div className="small muted">{p.rules.length} guardrail rules · blocks at severity {p.fail_on_severity_level}{p.is_system ? " · built-in" : ""}</div></div>
              <button type="button" className="btn btn-sm" disabled={setPolicies.isPending} onClick={() => save(a.policy_ids.filter((x) => x !== p.id), `${p.name} detached`)}><X className="ic" aria-hidden />Detach</button>
            </li>))}</ul>
        )}
        <div className="banner" style={{ marginTop: 14 }}>
          <Sparkles className="ic" aria-hidden />
          <span className="grow">Optimise uses the latest red-team gaps to recommend or compose a policy that closes them.</span>
          <button type="button" className="btn btn-sm" disabled={optimize.isPending} onClick={() => optimize.mutate({}, { onSuccess: setResult, onError: (e) => toast(errMsg(e), true) })}>{optimize.isPending ? "Analysing…" : "Optimise"}</button>
        </div>
        {result && (
          <div className="stack-sm" style={{ marginTop: 12 }}>
            <p className="small" style={{ margin: 0 }}>{result.report.summary}</p>
            {result.gaps.length > 0 && <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>{result.gaps.map((g) => <span key={g.category} className="tag bad">{humanize(g.category)}{g.block_rate_pct != null ? ` · ${g.block_rate_pct.toFixed(0)}% blocked` : ""}</span>)}</div>}
            {result.composed_policy && <div className="banner ok"><Check className="ic" aria-hidden /><span><b>{result.composed_policy.name}</b> — {result.composed_policy.note}</span></div>}
          </div>
        )}
      </section>
      <section>
        <h3 className="card-t" style={{ marginBottom: 6 }}>Recommended for this agent</h3>
        {recs.isError ? <ErrorState error={recs.error} compact /> : recs.isLoading ? <SkelRows rows={4} /> : !recs.data?.length ? <p className="small muted">No recommendations.</p> : (
          <ul className="list">{recs.data.map((r) => (
            <li key={r.policy.id}>
              <div style={{ minWidth: 0 }}>
                <b>{r.policy.name}</b> <span className="tag">{Math.round(r.score * 100) / 100} match</span>
                <div className="small muted">{r.reasons.slice(0, 2).join(" · ")}</div>
              </div>
              {r.attached || a.policy_ids.includes(r.policy.id) ? <Pill tone="accent" icon={Check}>Attached</Pill>
                : <button type="button" className="btn btn-sm btn-primary" disabled={setPolicies.isPending} onClick={() => save([...a.policy_ids, r.policy.id], `${r.policy.name} attached`)}><Plus className="ic" aria-hidden />Attach</button>}
            </li>))}</ul>
        )}
      </section>
    </div>
  );
}

function RedteamTab({ agent: a }: { agent: Agent }) {
  const evals = useEvaluations({ agent_id: a.id });
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const items = evals.data ?? [];
  const hasEndpoint = Boolean(a.runtime_config?.base_url);
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="small muted" style={{ margin: 0 }}>Each run attacks the agent with generated prompts. The trust score is the share of attacks blocked without over-blocking harmless questions.</p>
        <button type="button" className="btn btn-primary" disabled={!hasEndpoint} title={hasEndpoint ? undefined : "Add a chat endpoint first"} onClick={() => setOpen(true)}><Swords className="ic" aria-hidden />New red-team run</button>
      </div>
      {!hasEndpoint && <div className="banner wait"><Plug className="ic" aria-hidden /><span>This agent has no chat endpoint, so it can&apos;t be red-teamed yet. Re-onboard it with an endpoint.</span></div>}
      {evals.isError ? <ErrorState error={evals.error} compact /> : evals.isLoading ? <SkelRows rows={3} /> : !items.length ? (
        <Empty icon={Swords} title="No red-team runs yet">Run one to earn a trust score.</Empty>
      ) : (
        <div className="scroll-x"><table>
          <thead><tr><th>Started</th><th>Status</th><th>Trust score</th><th className="r">Attacks blocked</th><th className="r">False positives</th><th className="r">Prompts</th><th className="r">Duration</th></tr></thead>
          <tbody>{items.map((e) => (
            <tr key={e.id} className="clickable" onClick={() => router.push(`/governance/evaluations/${e.id}`)}>
              <td className="strong">{when(e.created_at)}</td>
              <td><EvalBadge status={e.status} progress={e.progress} total={e.prompts_total} /></td>
              <td><TrustScore score={e.trust_score} compact /></td>
              <td className="r">{e.block_rate_pct != null ? `${e.block_rate_pct.toFixed(1)}%` : "—"}</td>
              <td className="r">{e.summary.false_positive_rate_pct != null ? `${e.summary.false_positive_rate_pct.toFixed(1)}%` : "—"}</td>
              <td className="r">{e.prompts_total}</td>
              <td className="r muted">{e.started_at && e.finished_at ? ms(new Date(e.finished_at).getTime() - new Date(e.started_at).getTime()) : "—"}</td>
            </tr>))}</tbody>
        </table></div>
      )}
      <StartEvalModal open={open} onClose={() => setOpen(false)} agentId={a.id} onStarted={(e) => router.push(`/governance/evaluations/${e.id}`)} />
    </div>
  );
}

function GatewayTab({ agent: a }: { agent: Agent }) {
  const [conditional, setConditional] = useState(true);
  const gate = useGate(a.id, conditional);
  const dep = useAgentGateway(a.id);
  const models = useGatewayModels();
  const deploy = useDeployGateway(a.id);
  const revoke = useRevokeGateway();
  const toast = useToast();
  const [model, setModel] = useState("");
  const [created, setCreated] = useState<GatewayDeployResult | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const g = gate.data;
  const d = created ?? dep.data;

  const doDeploy = () => deploy.mutate({ model: model || undefined, allow_conditional: conditional }, {
    onSuccess: (r) => { setCreated(r); toast("Deployed behind the AI gateway"); },
    onError: (e) => toast(errMsg(e), true),
  });

  return (
    <div className="split-l" style={{ alignItems: "start" }}>
      <section>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
          <h3 className="card-t">Deployment gate</h3>
          {g && <Pill tone={g.allowed ? "accent" : "danger"} dot>{g.allowed ? "Gate open" : "Gate closed"}</Pill>}
        </div>
        <label className="check" style={{ marginBottom: 8 }}><input type="checkbox" checked={conditional} onChange={(e) => setConditional(e.target.checked)} />Accept &ldquo;approved with conditions&rdquo;</label>
        {gate.isError ? <ErrorState error={gate.error} compact /> : gate.isLoading ? <SkelRows rows={4} /> : (
          <ul className="checklist">{g?.checks.map((c) => (
            <li key={c.check}>
              <span className={`ci${c.passed ? "" : " bad"}`} aria-hidden>{c.passed ? <Check /> : <X />}</span>
              <div><b>{humanize(c.check)}</b><small>{c.detail}</small>{c.conditions?.length ? <small>Conditions: {c.conditions.join("; ")}</small> : null}</div>
              <span className="sr">{c.passed ? "Passed" : "Failed"}</span>
            </li>))}</ul>
        )}
      </section>
      <section className="stack-sm">
        <h3 className="card-t">AI gateway access</h3>
        {dep.isLoading ? <SkelRows rows={3} /> : d && d.status === "active" ? (
          <>
            <dl className="kv">
              <dt>Status</dt><dd><Pill tone="accent" dot>Active</Pill></dd>
              <dt>Model</dt><dd>{d.model}</dd>
              <dt>Allowed models</dt><dd>{d.allowed_models.join(", ") || "—"}</dd>
              <dt>Gateway URL</dt><dd className="row" style={{ gap: 6 }}><span className="ellipsis">{d.gateway_url}</span><CopyButton text={d.gateway_url} /></dd>
              <dt>Key</dt><dd>{d.key_prefix}…</dd>
              <dt>Deployed</dt><dd>{when(d.created_at)}</dd>
            </dl>
            {created?.api_key && (
              <div className="stack-sm">
                <div className="banner wait"><Network className="ic" aria-hidden /><span><b>Copy this key now.</b> It won&apos;t be shown again.</span></div>
                <div className="secret"><span className="grow">{created.api_key}</span><CopyButton text={created.api_key} /></div>
              </div>
            )}
            <div><button type="button" className="btn btn-danger" onClick={() => setConfirmRevoke(true)}><Power className="ic" aria-hidden />Revoke access</button></div>
          </>
        ) : (
          <>
            <p className="small muted" style={{ margin: 0 }}>Deploying issues a gateway key scoped to this agent. Every call through it runs the agent&apos;s policies.</p>
            <div className="field"><label htmlFor="gw-model">Model</label>
              <select id="gw-model" className="select-native" value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="">Agent default{a.model ? ` (${a.model})` : ""}</option>
                {(models.data?.models ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
              </select></div>
            <div><button type="button" className="btn btn-primary" disabled={!g?.allowed || deploy.isPending} onClick={doDeploy}><Network className="ic" aria-hidden />{deploy.isPending ? "Deploying…" : "Deploy to gateway"}</button></div>
            {g && !g.allowed && <span className="small muted">Clear every gate check to deploy.</span>}
          </>
        )}
      </section>
      <Modal open={confirmRevoke} onClose={() => setConfirmRevoke(false)} title="Revoke gateway access?" sub="The key stops working immediately. You can deploy again later."
        footer={<><button type="button" className="btn" onClick={() => setConfirmRevoke(false)}>Cancel</button>
          <button type="button" className="btn btn-danger" disabled={revoke.isPending} onClick={() => revoke.mutate(a.id, { onSuccess: () => { setCreated(null); setConfirmRevoke(false); toast("Gateway access revoked"); }, onError: (e) => toast(errMsg(e), true) })}>{revoke.isPending ? "Revoking…" : "Revoke"}</button></>}>
        <p className="small muted" style={{ margin: 0 }}>Applications calling {a.name} through the gateway will get 401 errors.</p>
      </Modal>
    </div>
  );
}

function EvidenceTab({ agent: a }: { agent: Agent }) {
  const ev = useEvidence(a.id);
  const e = ev.data;
  const download = () => {
    if (!e) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(e, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = `evidence-${a.external_id}.json`; link.click();
    URL.revokeObjectURL(url);
  };
  if (ev.isError) return <ErrorState error={ev.error} compact onRetry={() => ev.refetch()} />;
  if (ev.isLoading || !e) return <SkelRows rows={6} />;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="small muted" style={{ margin: 0 }}>Everything an auditor needs in one file: risk decision, red-team results, guardrail decisions, policies and lifecycle. Generated {when(e.generated_at)}.</p>
        <button type="button" className="btn" onClick={download}><Download className="ic" aria-hidden />Download JSON</button>
      </div>
      <div className="grid-3">
        <section className="card" style={{ padding: 16 }}>
          <h3 className="card-t" style={{ marginBottom: 10 }}>Risk decision</h3>
          {e.risk_assessment ? (
            <dl className="kv">
              <dt>Tier</dt><dd><TierBadge tier={e.risk_assessment.tier} /></dd>
              <dt>Decision</dt><dd><DecisionBadge decision={e.risk_assessment.decision} /></dd>
              <dt>Decided by</dt><dd>{e.risk_assessment.decided_by ?? "—"}</dd>
              <dt>Controls</dt><dd>{e.risk_assessment.required_controls.length}</dd>
              <dt>Assumptions</dt><dd>{e.risk_assessment.assumptions.length}</dd>
            </dl>
          ) : <p className="small muted">No assessment yet.</p>}
        </section>
        <section className="card" style={{ padding: 16 }}>
          <h3 className="card-t" style={{ marginBottom: 10 }}>Testing</h3>
          <dl className="kv">
            <dt>Trust score</dt><dd><TrustScore score={e.trust_score} compact /></dd>
            <dt>Red-team runs</dt><dd>{e.evaluations.length}</dd>
            <dt>Guardrail checks</dt><dd>{e.guardrail_evaluations.count} <span className="muted">· {e.guardrail_evaluations.failed} failed</span></dd>
            <dt>Policy violations</dt><dd style={{ color: e.policy_violations ? "var(--danger)" : undefined }}>{e.policy_violations}</dd>
          </dl>
        </section>
        <section className="card" style={{ padding: 16 }}>
          <h3 className="card-t" style={{ marginBottom: 10 }}>Production</h3>
          <dl className="kv">
            <dt>Stage</dt><dd><LifecycleBadge status={e.agent_status} /></dd>
            <dt>Policies</dt><dd>{e.policies.map((p) => p.name).join(", ") || "—"}</dd>
            <dt>Gateway</dt><dd>{e.gateway ? `${e.gateway.model} · ${e.gateway.status}` : "Not deployed"}</dd>
            <dt>Deployed by</dt><dd>{e.gateway?.deployed_by ?? "—"}</dd>
          </dl>
        </section>
      </div>
      <section>
        <h3 className="card-t" style={{ marginBottom: 6 }}>Latest guardrail decisions</h3>
        {!e.guardrail_evaluations.latest.length ? <p className="small muted">None recorded.</p> : (
          <div className="scroll-x"><table>
            <thead><tr><th>When</th><th>Result</th><th>Phase</th><th>Source</th><th>Failed checks</th></tr></thead>
            <tbody>{e.guardrail_evaluations.latest.map((g) => (
              <tr key={g.id}><td>{when(g.at)}</td><td><Pill tone={g.passed ? "accent" : "danger"} dot>{g.passed ? "Passed" : "Blocked"}</Pill></td><td className="muted">{humanize(g.phase)}</td><td className="muted">{humanize(g.source)}</td><td>{g.failed_checks.map(humanize).join(", ") || "—"}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}
