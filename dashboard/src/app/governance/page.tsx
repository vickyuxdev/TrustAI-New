"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ClipboardCheck, Library, ShieldCheck, Swords, TriangleAlert } from "lucide-react";
import { CheckRing, Ring } from "@/components/charts";
import { LIFE_LABEL, LifecycleBadge, TierBadge } from "@/components/gov";
import { Card, CardHeader, Empty, ErrorState, Kpi, MoreLink, PageHead, Skel, SkelRows } from "@/components/ui";
import { useAgents, useAssessments, useEvaluations, useEvents, useOverview, type LifecycleStatus } from "@/lib/governance";
import { ago, compact, humanize } from "@/lib/format";

const BAR = 95;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const PATH: LifecycleStatus[] = ["registered", "onboarded", "assessed", "evaluated", "approved", "deployed"];

/** Horizontal meter with a tick at the 95 release bar. */
function TrustMeter({ score, width = 88, bare }: { score: number | null; width?: number; bare?: boolean }) {
  if (score == null) return <span className="muted">Not tested</span>;
  const f = Math.max(0, Math.min(1, (score - 50) / 50));
  const c = score >= BAR ? "var(--accent)" : score >= 85 ? "var(--wait)" : "var(--danger)";
  return (
    <span className="gv-meter">
      {!bare && <b className="num" style={{ color: score >= BAR ? undefined : c }}>{score.toFixed(1)}</b>}
      <span className="gv-track" style={{ width }} aria-hidden><i style={{ width: `${f * 100}%`, background: c }} /><em style={{ left: `${((BAR - 50) / 50) * 100}%` }} /></span>
    </span>
  );
}

export default function GovernancePage() {
  const router = useRouter();
  const ov = useOverview();
  const agentsQ = useAgents({ limit: 200 });
  const pending = useAssessments({ status: "classified" });
  const evals = useEvaluations();
  const events = useEvents({ limit: 20 });
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
  const nameOf = (id: string) => agents.find((a) => a.id === id)?.name ?? "Agent";

  type Item = { key: string; sev: "high" | "med" | "low"; title: string; sub: string; href: string; cta: string };
  const todo: Item[] = [
    ...by("suspended").map((a) => ({ key: "s" + a.id, sev: "high" as const, title: `${a.name} is suspended`, sub: `Tier ${a.risk_tier ?? "—"} · trust ${a.trust_score ?? "—"}`, href: `/governance/agents/${a.id}`, cta: "Review" })),
    ...(pending.data ?? []).map((x) => ({ key: "d" + x.id, sev: "med" as const, title: `Risk decision needed · ${nameOf(x.agent_id)}`, sub: `Tier ${x.risk_tier} · submitted ${ago(x.submitted_at)}`, href: `/governance/risk/${x.id}`, cta: "Decide" })),
    ...agents.filter((a) => a.trust_score != null && a.trust_score < BAR && ["evaluated", "approved"].includes(a.lifecycle_status)).map((a) => ({ key: "t" + a.id, sev: "med" as const, title: `${a.name} below trust bar`, sub: `Trust ${a.trust_score?.toFixed(1)} of ${BAR} required`, href: `/governance/agents/${a.id}`, cta: "Review" })),
    ...agents.filter((a) => a.lifecycle_status === "onboarded").map((a) => ({ key: "o" + a.id, sev: "low" as const, title: `${a.name} not risk-assessed`, sub: "Onboarded, no risk tier yet", href: `/governance/agents/${a.id}`, cta: "Assess" })),
    ...running.map((e) => ({ key: "r" + e.id, sev: "low" as const, title: `Red-team in progress · ${nameOf(e.agent_id)}`, sub: `${e.progress} of ${e.prompts_total} prompts graded`, href: `/governance/evaluations/${e.id}`, cta: "View" })),
  ];
  const ranked = [...agents].sort((a, b) => (b.risk_tier ?? 0) - (a.risk_tier ?? 0) || (a.trust_score ?? 0) - (b.trust_score ?? 0));

  return (
    <>
      <PageHead title="Governance" sub="Risk, testing and release status for every AI agent."
        actions={<Link href="/governance/agents" className="btn btn-primary"><Library className="ic" aria-hidden />Agent registry</Link>} />

      {ov.isError ? <Card><ErrorState error={ov.error} onRetry={() => ov.refetch()} /></Card> : (
        <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Governance figures">
          <Kpi icon={Library} label="Agents governed" value={ov.isLoading ? <Skel w={40} h={22} /> : compact(o?.agents_total)}
            vis={agents.length ? <Ring size={34} stroke={5} ariaLabel="Agents by stage" slices={[
              { name: "Live or approved", value: live, color: "var(--accent)" }, { name: "In review", value: review, color: "var(--accent-line)" },
              { name: "Onboarding", value: early, color: "var(--line-2)" }, { name: "Blocked", value: blocked, color: "var(--danger)" }]} /> : undefined}
            foot={`${live} live or approved · ${review} in review · ${early} onboarding`} />
          <Kpi icon={ShieldCheck} label="Average trust score" value={o?.average_trust_score != null ? o.average_trust_score.toFixed(1) : "—"}
            vis={o?.average_trust_score != null ? <TrustMeter score={o.average_trust_score} width={88} bare /> : undefined}
            foot={`${meeting} of ${scored.length} tested agents meet the ${BAR} release bar`} />
          <Kpi icon={ShieldCheck} label="Guardrail checks · 24h" value={ov.isLoading ? <Skel w={60} h={22} /> : compact(checks)}
            vis={checks ? <CheckRing ok={viol / checks < 0.01} size={30} /> : undefined}
            foot={`${viol} blocked · ${checks ? (100 - (viol / checks) * 100).toFixed(2) : "100"}% passed`} />
          <Kpi icon={TriangleAlert} label="Open items" tone={todo.some((t) => t.sev === "high") ? "bad" : undefined} value={agentsQ.isLoading ? <Skel w={40} h={22} /> : String(todo.length)}
            foot={`${plural(o?.decisions_pending ?? 0, "decision", "decisions")} · ${plural(by("suspended").length, "suspended agent", "suspended agents")} · ${plural(running.length, "test running", "tests running")}`} />
        </section>
      )}

      <Card labelledBy="t-life">
        <CardHeader id="t-life" title="Lifecycle" sub="Agents at each stage on the way to production" action={<MoreLink href="/governance/agents">Agent registry</MoreLink>} />
        <div className="gv-life">
          {PATH.map((s, i) => {
            const list = by(s);
            return (
              <div key={s} className={list.length ? "on" : ""}>
                <span className="gv-l-lbl"><span className="gv-l-step">{i + 1}</span>{LIFE_LABEL[s]}</span>
                <b className="num">{agentsQ.isLoading ? "—" : list.length}</b>
                <span className="gv-l-names" title={list.map((a) => a.name).join(", ")}>{list.length ? list.map((a) => a.name).join(", ") : "None"}</span>
              </div>
            );
          })}
          <div className={`gv-l-off${blocked ? " on" : ""}`}>
            <span className="gv-l-lbl">Suspended or retired</span>
            <b className="num">{agentsQ.isLoading ? "—" : blocked}</b>
            <span className="gv-l-names">{[...by("suspended"), ...by("retired")].map((a) => a.name).join(", ") || "None"}</span>
          </div>
        </div>
      </Card>

      <div className="gv-grid">
        <Card labelledBy="t-ag">
          <CardHeader id="t-ag" title="Agents" sub="Highest risk first" action={<MoreLink href="/governance/agents">View all</MoreLink>} />
          <div className="scroll-y sticky-head gv-fill" style={{ marginTop: 12 }}>
            {agentsQ.isError ? <ErrorState error={agentsQ.error} compact /> : agentsQ.isLoading ? <SkelRows rows={8} /> : !agents.length ? <Empty icon={Library} title="No agents yet" /> : (
              <table>
                <thead><tr><th>Agent</th><th>Stage</th><th>Risk tier</th><th>Trust score</th><th className="r">Policies</th><th className="r">Updated</th></tr></thead>
                <tbody>
                  {ranked.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => router.push(`/governance/agents/${a.id}`)}>
                      <td><b>{a.name}</b><div className="sub">{a.model ?? "—"} · {a.owner?.split("@")[0] ?? "no owner"}</div></td>
                      <td><LifecycleBadge status={a.lifecycle_status} /></td>
                      <td><TierBadge tier={a.risk_tier} /></td>
                      <td><TrustMeter score={a.trust_score} /></td>
                      <td className="r num">{a.policy_ids.length}</td>
                      <td className="r muted">{ago(a.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>

        <div className="gv-side">
          <Card labelledBy="t-todo">
            <CardHeader id="t-todo" title="Needs attention" sub={`${todo.length} open items`} bordered />
            <div className="scroll-y gv-fill">
              {agentsQ.isLoading ? <SkelRows rows={4} /> : !todo.length ? <Empty icon={ClipboardCheck} title="Nothing open" /> : (
                <ul className="gv-list">
                  {todo.map((t) => (
                    <li key={t.key}>
                      <span className={`gv-sev ${t.sev}`} aria-label={`${t.sev} priority`} />
                      <div><b>{t.title}</b><small>{t.sub}</small></div>
                      <Link href={t.href} className="gv-link">{t.cta}</Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Card>
          <Card labelledBy="t-act">
            <CardHeader id="t-act" title="Recent activity" bordered action={<MoreLink href="/governance/events">Audit log</MoreLink>} />
            <div className="scroll-y gv-fill">
              {events.isLoading ? <SkelRows rows={4} /> : !events.data?.length ? <Empty icon={Swords} title="No activity yet" /> : (
                <ul className="gv-list">
                  {events.data.map((e) => {
                    const sev = e.severity.toLowerCase();
                    return (
                      <li key={e.id}>
                        <span className={`gv-sev ${["critical", "high", "error"].includes(sev) ? "high" : ["medium", "warning"].includes(sev) ? "med" : "none"}`} aria-hidden />
                        <div><b>{humanize(e.event_type)}</b><small>{e.agent_id ? nameOf(e.agent_id) : "—"} · {e.actor.split("@")[0]}</small></div>
                        <span className="gv-time">{ago(e.created_at)}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
