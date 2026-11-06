"use client";
import Link from "next/link";
import { Activity, ClipboardCheck, Library, Network, ShieldAlert, ShieldCheck, Swords } from "lucide-react";
import { AgentLink, AssessmentBadge, EvalBadge, LIFE_LABEL, SeverityBadge, TIER_LABEL, TrustScore } from "@/components/gov";
import { Card, CardHeader, Empty, ErrorState, Kpi, MoreLink, PageHead, SkelRows } from "@/components/ui";
import { LIFECYCLE_STATUSES, useAgentIndex, useAssessments, useEvaluations, useEvents, useOverview } from "@/lib/governance";
import { ago, compact, humanize } from "@/lib/format";

const LIFE_COLOR: Record<string, string> = {
  registered: "var(--c5)", onboarded: "var(--s3)", assessed: "var(--c2)", evaluated: "var(--c4)",
  approved: "var(--s2)", deployed: "var(--accent)", suspended: "var(--danger)", retired: "var(--line-2)",
};
const TIER_COLOR: Record<string, string> = { "1": "var(--accent)", "2": "var(--c2)", "3": "var(--c3)", "4": "var(--danger)" };

export default function GovernancePage() {
  const ov = useOverview();
  const index = useAgentIndex();
  const pending = useAssessments({ status: "classified" });
  const evals = useEvaluations();
  const events = useEvents({ limit: 30 });
  const o = ov.data;
  const lifeMax = Math.max(1, ...LIFECYCLE_STATUSES.map((s) => o?.agents_by_status[s] ?? 0));
  const tiers = ["1", "2", "3", "4"];
  const tierTotal = tiers.reduce((a, t) => a + (o?.agents_by_tier[t] ?? 0), 0);

  return (
    <>
      <PageHead title="Governance" sub="Onboard, risk-assess, guard, red-team and gate every AI agent before it reaches users."
        actions={<Link href="/governance/agents" className="btn btn-primary"><Library className="ic" aria-hidden />Agent registry</Link>} />

      {ov.isError ? <Card><ErrorState error={ov.error} onRetry={() => ov.refetch()} /></Card> : (
        <section className="kpis" aria-label="Governance figures">
          <Kpi icon={Library} label="Agents governed" value={ov.isLoading ? "—" : compact(o?.agents_total)} foot={`${o?.agents_by_status.deployed ?? 0} deployed · ${o?.agents_by_status.approved ?? 0} approved`} />
          <Kpi icon={ShieldCheck} label="Average trust score" value={o?.average_trust_score != null ? o.average_trust_score.toFixed(1) : "—"} foot="From the latest red-team run per agent" />
          <Kpi icon={ClipboardCheck} label="Decisions pending" tone={o?.decisions_pending ? "wait" : undefined} value={ov.isLoading ? "—" : String(o?.decisions_pending ?? 0)} link={{ href: "/governance/risk", label: "Review" }} foot={o?.decisions_pending ? "Risk assessments waiting on a person" : "Nothing waiting"} />
          <Kpi icon={Swords} label="Red-team runs" value={ov.isLoading ? "—" : String(o?.evaluations_running ?? 0)} foot="Running or queued now" />
          <Kpi icon={Activity} label="Guardrail checks · 24h" value={ov.isLoading ? "—" : compact(o?.guardrail_checks_24h)} foot={<><b style={{ color: o?.policy_violations_24h ? "var(--danger)" : "var(--text-2)", fontWeight: 600 }}>{o?.policy_violations_24h ?? 0}</b>&nbsp;policy violations</>} />
          <Kpi icon={Network} label="Gateway deployments" value={ov.isLoading ? "—" : String(o?.gateway_deployments_active ?? 0)} link={{ href: "/governance/gateway", label: "View" }} foot="Agents live behind the AI gateway" />
        </section>
      )}

      <div className="split-l">
        <Card labelledBy="t-life">
          <CardHeader id="t-life" title="Agents by lifecycle stage" sub="Where every agent sits on the path to production" action={<MoreLink href="/governance/agents">Registry</MoreLink>} />
          <div className="card-b">
            {ov.isLoading ? <SkelRows rows={6} /> : (
              <ul className="stack-sm" style={{ gap: 10 }}>
                {LIFECYCLE_STATUSES.map((s) => {
                  const n = o?.agents_by_status[s] ?? 0;
                  return (
                    <li key={s} style={{ display: "grid", gridTemplateColumns: "110px minmax(0,1fr) 40px", gap: 12, alignItems: "center" }}>
                      <span className="small" style={{ color: "var(--text-2)", fontWeight: 500 }}>{LIFE_LABEL[s]}</span>
                      <span className="bar-track" style={{ height: 8, borderRadius: 4 }}><i style={{ width: `${(n / lifeMax) * 100}%`, background: LIFE_COLOR[s], borderRadius: 4 }} /></span>
                      <b className="num r">{n}</b>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Card>
        <Card labelledBy="t-tier">
          <CardHeader id="t-tier" title="Risk tiers" sub={`${tierTotal} assessed agents`} action={<MoreLink href="/governance/risk">Assessments</MoreLink>} />
          <div className="card-b" style={{ gap: 14 }}>
            <div className="sharebar" style={{ height: 12 }} aria-hidden>
              {tiers.filter((t) => (o?.agents_by_tier[t] ?? 0) > 0).map((t) => <i key={t} style={{ flex: `${o?.agents_by_tier[t]} 1 0`, background: TIER_COLOR[t] }} />)}
              {!tierTotal && <i style={{ flex: 1, background: "var(--hover)" }} />}
            </div>
            <ul className="list">
              {tiers.map((t) => (
                <li key={t}>
                  <span className="row"><i style={{ width: 8, height: 8, borderRadius: 2, background: TIER_COLOR[t], display: "inline-block" }} aria-hidden /><b>Tier {t}</b><span className="muted">{TIER_LABEL[+t]}</span></span>
                  <b className="num">{o?.agents_by_tier[t] ?? 0}</b>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      </div>

      <div className="grid-3">
        <Card labelledBy="t-pend" style={{ height: 340 }}>
          <CardHeader id="t-pend" title="Waiting on a decision" sub="Classified assessments need a human approve or reject" bordered />
          <div className="scroll-y" style={{ flex: 1, minHeight: 0 }}>
            {pending.isLoading ? <SkelRows rows={4} /> : !pending.data?.length ? <Empty icon={ClipboardCheck} title="Nothing waiting">Every classified assessment has a decision.</Empty> : (
              <ul className="list" style={{ padding: "0 18px" }}>
                {pending.data.map((a) => (
                  <li key={a.id}>
                    <div style={{ minWidth: 0 }}><Link href={`/governance/risk/${a.id}`} className="strong">{index[a.agent_id]?.name ?? "Agent"}</Link><div className="small muted">Tier {a.risk_tier ?? "—"} · submitted {ago(a.submitted_at)}</div></div>
                    <AssessmentBadge status={a.status} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
        <Card labelledBy="t-ev" style={{ height: 340 }}>
          <CardHeader id="t-ev" title="Recent red-team runs" sub="Trust score against the 95 release bar" bordered action={<MoreLink href="/governance/evaluations">All runs</MoreLink>} />
          <div className="scroll-y" style={{ flex: 1, minHeight: 0 }}>
            {evals.isLoading ? <SkelRows rows={4} /> : !evals.data?.length ? <Empty icon={Swords} title="No runs yet">Start a red-team run from an agent&apos;s page.</Empty> : (
              <ul className="list" style={{ padding: "0 18px" }}>
                {evals.data.slice(0, 12).map((e) => (
                  <li key={e.id}>
                    <div style={{ minWidth: 0 }}><Link href={`/governance/evaluations/${e.id}`} className="strong">{index[e.agent_id]?.name ?? "Agent"}</Link><div className="small muted">{e.prompts_total} prompts · {ago(e.created_at)}</div></div>
                    {e.status === "completed" ? <TrustScore score={e.trust_score} compact /> : <EvalBadge status={e.status} progress={e.progress} total={e.prompts_total} />}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
        <Card labelledBy="t-evt" style={{ height: 340 }}>
          <CardHeader id="t-evt" title="Audit trail" sub="Lifecycle, decisions, deployments, violations" bordered action={<MoreLink href="/governance/events">All events</MoreLink>} />
          <div className="scroll-y" style={{ flex: 1, minHeight: 0 }}>
            {events.isError ? <div className="card-b"><ErrorState error={events.error} compact /></div> : events.isLoading ? <SkelRows rows={5} /> : !events.data?.length ? <Empty icon={ShieldAlert} title="No events yet" /> : (
              <ul className="list" style={{ padding: "0 18px" }}>
                {events.data.map((e) => (
                  <li key={e.id}>
                    <div style={{ minWidth: 0 }}><b className="ellipsis" style={{ display: "block" }}>{humanize(e.event_type)}</b><div className="small muted ellipsis"><AgentLink agent={e.agent_id ? index[e.agent_id] : undefined} id={e.agent_id} /> · {e.actor} · {ago(e.created_at)}</div></div>
                    <SeverityBadge severity={e.severity} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}
