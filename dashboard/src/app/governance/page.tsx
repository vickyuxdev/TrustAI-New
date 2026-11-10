"use client";
import Link from "next/link";
import { ArrowRight, ClipboardCheck, Gauge as GaugeIcon, Library, PauseCircle, ShieldAlert, ShieldCheck, Swords, TriangleAlert } from "lucide-react";
import { CheckRing, Ring } from "@/components/charts";
import { LIFE_LABEL, TIER_LABEL } from "@/components/gov";
import { Card, CardHeader, Empty, ErrorState, Kpi, MoreLink, PageHead, Skel, SkelRows } from "@/components/ui";
import { useAgents, useAssessments, useEvaluations, useEvents, useOverview, type LifecycleStatus } from "@/lib/governance";
import { ago, compact, humanize } from "@/lib/format";

const BAR = 95;
const PATH: LifecycleStatus[] = ["registered", "onboarded", "assessed", "evaluated", "approved", "deployed"];
const STAGE_HINT: Record<string, string> = {
  registered: "Known, not set up", onboarded: "Profile & tools captured", assessed: "Risk tier assigned",
  evaluated: "Red-teamed", approved: "Cleared by a person", deployed: "Live behind the gateway",
};
const BUCKETS = [{ id: "none", label: "No score", test: (s: number | null) => s == null }, { id: "lt80", label: "Below 80", test: (s: number | null) => s != null && s < 80 },
  { id: "80", label: "80–90", test: (s: number | null) => s != null && s >= 80 && s < 90 }, { id: "90", label: "90–95", test: (s: number | null) => s != null && s >= 90 && s < BAR },
  { id: "95", label: "95+", test: (s: number | null) => s != null && s >= BAR }];

/** Each agent's trust score as a dot on a 70–100 strip, with the 95 release bar marked. */
function TrustStrip({ scores }: { scores: number[] }) {
  const x = (v: number) => 4 + ((Math.max(70, Math.min(100, v)) - 70) / 30) * 92;
  return (
    <svg width={100} height={30} viewBox="0 0 100 30" aria-hidden>
      <line x1={4} x2={96} y1={18} y2={18} stroke="var(--line-2)" strokeWidth={2} strokeLinecap="round" />
      <line x1={x(BAR)} x2={x(BAR)} y1={9} y2={26} stroke="var(--text-3)" strokeWidth={1.5} strokeLinecap="round" />
      <text x={x(BAR)} y={7} textAnchor="middle" className="ax" style={{ fontSize: 8.5 }}>95</text>
      {scores.map((s, i) => <circle key={i} cx={x(s)} cy={18} r={3.6} fill={s >= BAR ? "var(--accent)" : s >= 85 ? "var(--wait)" : "var(--danger)"} stroke="var(--panel)" strokeWidth={1.5} />)}
    </svg>
  );
}

export default function GovernancePage() {
  const ov = useOverview();
  const agentsQ = useAgents({ limit: 200 });
  const pending = useAssessments({ status: "classified" });
  const evals = useEvaluations();
  const events = useEvents({ limit: 30 });
  const o = ov.data;
  const agents = agentsQ.data?.items ?? [];
  const by = (s: LifecycleStatus) => agents.filter((a) => a.lifecycle_status === s);
  const scored = agents.filter((a) => a.trust_score != null);
  const meeting = scored.filter((a) => (a.trust_score ?? 0) >= BAR).length;
  const live = by("deployed").length + by("approved").length;
  const review = by("assessed").length + by("evaluated").length;
  const early = by("registered").length + by("onboarded").length;
  const blocked = by("suspended").length + by("retired").length;
  const viol = o?.policy_violations_24h ?? 0, checks = o?.guardrail_checks_24h ?? 0;
  const running = (evals.data ?? []).filter((e) => e.status === "running" || e.status === "queued");

  // Things a person should act on, most urgent first.
  type Item = { key: string; tone: "bad" | "wait" | "info"; icon: typeof ShieldAlert; title: string; sub: string; href: string; cta: string };
  const todo: Item[] = [
    ...by("suspended").map((a) => ({ key: "s" + a.id, tone: "bad" as const, icon: PauseCircle, title: `${a.name} is suspended`, sub: `Tier ${a.risk_tier ?? "—"} · trust ${a.trust_score ?? "—"} · blocked from serving traffic`, href: `/governance/agents/${a.id}`, cta: "Open" })),
    ...(pending.data ?? []).map((x) => ({ key: "d" + x.id, tone: "wait" as const, icon: ClipboardCheck, title: `Risk decision for ${agents.find((a) => a.id === x.agent_id)?.name ?? "an agent"}`, sub: `Classified Tier ${x.risk_tier} · submitted ${ago(x.submitted_at)}`, href: `/governance/risk/${x.id}`, cta: "Decide" })),
    ...agents.filter((a) => a.trust_score != null && a.trust_score < BAR && ["evaluated", "approved"].includes(a.lifecycle_status)).map((a) => ({ key: "t" + a.id, tone: "wait" as const, icon: TriangleAlert, title: `${a.name} is below the ${BAR} trust bar`, sub: `Trust ${a.trust_score?.toFixed(1)} · attach policies or re-run red-team`, href: `/governance/agents/${a.id}`, cta: "Improve" })),
    ...agents.filter((a) => a.lifecycle_status === "onboarded").map((a) => ({ key: "o" + a.id, tone: "info" as const, icon: ShieldAlert, title: `${a.name} has no risk tier yet`, sub: "Onboarded · start the risk questionnaire", href: `/governance/agents/${a.id}`, cta: "Assess" })),
    ...running.map((e) => ({ key: "r" + e.id, tone: "info" as const, icon: Swords, title: `Red-team running on ${agents.find((a) => a.id === e.agent_id)?.name ?? "an agent"}`, sub: `${e.progress} of ${e.prompts_total} prompts graded`, href: `/governance/evaluations/${e.id}`, cta: "Watch" })),
  ];

  return (
    <>
      <PageHead title="Governance" sub="Onboard, risk-assess, guard, red-team and gate every AI agent before it reaches users."
        actions={<Link href="/governance/agents" className="btn btn-primary"><Library className="ic" aria-hidden />Agent registry</Link>} />

      {ov.isError ? <Card><ErrorState error={ov.error} onRetry={() => ov.refetch()} /></Card> : (
        <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Governance figures">
          <Kpi icon={Library} label="Agents governed" value={ov.isLoading ? <Skel w={40} h={22} /> : compact(o?.agents_total)}
            vis={agents.length ? <Ring size={34} stroke={5} ariaLabel="Agents by stage" slices={[
              { name: "Live or approved", value: live, color: "var(--accent)" }, { name: "In review", value: review, color: "var(--s2)" },
              { name: "Onboarding", value: early, color: "var(--s3)" }, { name: "Blocked", value: blocked, color: "var(--danger)" }]} /> : undefined}
            foot={`${live} live or approved · ${review} in review · ${blocked} blocked`} />
          <Kpi icon={ShieldCheck} label="Average trust score" value={o?.average_trust_score != null ? o.average_trust_score.toFixed(1) : "—"}
            vis={scored.length ? <TrustStrip scores={scored.map((a) => a.trust_score as number)} /> : undefined}
            foot={`${meeting} of ${scored.length} scored agents meet the ${BAR} bar`} />
          <Kpi icon={GaugeIcon} label="Guardrail checks · 24h" value={ov.isLoading ? <Skel w={60} h={22} /> : compact(checks)}
            vis={checks ? <CheckRing ok={viol / checks < 0.01} size={30} /> : undefined}
            foot={<><b style={{ color: viol ? "var(--danger)" : "var(--text-2)", fontWeight: 600 }}>{viol}</b>&nbsp;blocked as violations · {checks ? ((viol / checks) * 100).toFixed(2) : "0"}%</>} />
          <Kpi icon={TriangleAlert} label="Needs action" tone={todo.some((t) => t.tone === "bad") ? "bad" : undefined}
            value={agentsQ.isLoading ? <Skel w={40} h={22} /> : String(todo.length)}
            vis={<div className="gv-dots" aria-hidden>{todo.slice(0, 8).map((t) => <i key={t.key} className={t.tone} />)}</div>}
            foot={`${o?.decisions_pending ?? 0} decision · ${blocked} suspended · ${running.length} run in progress`} />
        </section>
      )}

      {/* Path to production */}
      <Card labelledBy="t-path">
        <CardHeader id="t-path" title="Path to production" sub="Every governed agent by lifecycle stage" action={<MoreLink href="/governance/agents">Agent registry</MoreLink>} />
        <div className="gv-path">
          <ol>
            {PATH.map((s, i) => {
              const list = by(s);
              return (
                <li key={s} className={list.length ? "has" : ""} style={{ ["--lvl" as string]: i } as React.CSSProperties}>
                  <div className="gv-st-h"><span className="gv-st-n">{i + 1}</span><b>{LIFE_LABEL[s]}</b></div>
                  <div className="gv-st-c num">{agentsQ.isLoading ? "—" : list.length}</div>
                  <small>{STAGE_HINT[s]}</small>
                  <div className="gv-st-a">
                    {list.slice(0, 2).map((a) => <Link key={a.id} href={`/governance/agents/${a.id}`} title={a.name}>{a.name}</Link>)}
                    {list.length > 2 && <span>+{list.length - 2} more</span>}
                  </div>
                </li>
              );
            })}
          </ol>
          <div className={`gv-off${blocked ? " has" : ""}`}>
            <div className="gv-st-h"><PauseCircle className="ic" aria-hidden /><b>Off the path</b></div>
            <div className="gv-st-c num">{agentsQ.isLoading ? "—" : blocked}</div>
            <small>{by("suspended").length} suspended · {by("retired").length} retired</small>
            <div className="gv-st-a">{[...by("suspended"), ...by("retired")].slice(0, 2).map((a) => <Link key={a.id} href={`/governance/agents/${a.id}`}>{a.name}</Link>)}</div>
          </div>
        </div>
      </Card>

      <div className="gv-row">
        {/* Risk vs trust */}
        <Card labelledBy="t-mx">
          <CardHeader id="t-mx" title="Risk vs trust" sub={`Risk tier against latest trust score · aim for the 95+ column${agents.some((a) => a.risk_tier == null) ? ` · ${agents.filter((a) => a.risk_tier == null).length} unassessed not shown` : ""}`} action={<MoreLink href="/governance/risk">Assessments</MoreLink>} />
          <div className="gv-mx">
            {agentsQ.isLoading ? <SkelRows rows={4} /> : (
              <table>
                <thead><tr><th />{BUCKETS.map((b) => <th key={b.id} className={b.id === "95" ? "ok" : ""}>{b.label}</th>)}</tr></thead>
                <tbody>
                  {[4, 3, 2, 1].map((t) => (
                    <tr key={t}>
                      <th><b>Tier {t}</b><span>{TIER_LABEL[t]}</span></th>
                      {BUCKETS.map((b) => {
                        const cell = agents.filter((a) => a.risk_tier === t && b.test(a.trust_score));
                        const danger = cell.length && t >= 3 && (b.id === "lt80" || b.id === "80");
                        const warn = cell.length && !danger && (b.id !== "95") && (t >= 3 || b.id === "lt80");
                        return (
                          <td key={b.id} className={`${b.id === "95" ? "okcol" : ""}${danger ? " bad" : warn ? " wait" : cell.length ? " has" : ""}`}>
                            {cell.map((a) => <Link key={a.id} href={`/governance/agents/${a.id}`} className="gv-chip" title={`${a.name} · trust ${a.trust_score ?? "—"}`}>{a.name.replace(/ Agent$/, "")}{a.trust_score != null && <em>{a.trust_score.toFixed(0)}</em>}</Link>)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>

        {/* Attention */}
        <Card labelledBy="t-todo">
          <CardHeader id="t-todo" title="Needs your attention" sub={todo.length ? `${todo.length} items, most urgent first` : "Nothing to act on"} bordered />
          <div className="scroll-y gv-scroll">
            {agentsQ.isLoading ? <SkelRows rows={5} /> : !todo.length ? <Empty icon={ShieldCheck} title="All clear">Every agent is assessed, tested and within its trust bar.</Empty> : (
              <ul className="gv-todo">
                {todo.map((t) => (
                  <li key={t.key}>
                    <span className={`gv-ti ${t.tone}`} aria-hidden><t.icon className="ic" /></span>
                    <div className="gv-tt"><b>{t.title}</b><small>{t.sub}</small></div>
                    <Link href={t.href} className="gv-cta">{t.cta}<ArrowRight className="ic" aria-hidden /></Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        {/* Activity */}
        <Card labelledBy="t-act">
          <CardHeader id="t-act" title="Activity" sub="Audit trail · newest first" bordered action={<MoreLink href="/governance/events">All events</MoreLink>} />
          <div className="scroll-y gv-scroll">
            {events.isError ? <div className="card-b"><ErrorState error={events.error} compact /></div> : events.isLoading ? <SkelRows rows={6} /> : !events.data?.length ? <Empty icon={ShieldAlert} title="No events yet" /> : (
              <ol className="gv-tl">
                {events.data.map((e) => {
                  const sev = e.severity.toLowerCase();
                  const tone = ["critical", "high", "error"].includes(sev) ? "bad" : ["medium", "warning"].includes(sev) ? "wait" : "";
                  const a = agents.find((x) => x.id === e.agent_id);
                  return (
                    <li key={e.id} className={tone}>
                      <b>{humanize(e.event_type)}</b>
                      <small>{a ? <Link href={`/governance/agents/${a.id}`}>{a.name}</Link> : "—"} · {e.actor.split("@")[0]} · {ago(e.created_at)}</small>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}

