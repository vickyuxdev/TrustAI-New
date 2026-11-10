"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { ClipboardCheck, Library, ShieldCheck, TriangleAlert } from "lucide-react";
import { CheckRing, Ring, StackedBars } from "@/components/charts";
import { LIFE_LABEL, TIER_LABEL } from "@/components/gov";
import { Card, CardHeader, Empty, ErrorState, Kpi, MoreLink, PageHead, Skel, SkelRows } from "@/components/ui";
import { useAgents, useAssessments, useEvaluations, useEvents, useOverview, type LifecycleStatus } from "@/lib/governance";
import { ago, compact, humanize } from "@/lib/format";

const BAR = 95;
const STAGES: LifecycleStatus[] = ["registered", "onboarded", "assessed", "evaluated", "approved", "deployed", "suspended"];
// Risk tiers use the brand's evergreen ramp (light → dark = low → high); red is kept for the critical tier only.
const TIER_COLOR: Record<number, string> = { 1: "var(--g1)", 2: "var(--g2)", 3: "var(--g3)", 4: "var(--danger)" };
const pass = (v: number) => (v >= BAR ? "var(--accent)" : "var(--danger)");
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const longFmt = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });

/** Small KPI meter with a tick at the 95 release bar. */
function TrustMeter({ score }: { score: number }) {
  const f = Math.max(0, Math.min(1, (score - 50) / 50));
  const c = score >= BAR ? "var(--accent)" : "var(--wait)";
  return <span className="gv-track" style={{ width: 88 }} aria-hidden><i style={{ width: `${f * 100}%`, background: c }} /><em style={{ left: `${((BAR - 50) / 50) * 100}%` }} /></span>;
}

export default function GovernancePage() {
  const ov = useOverview();
  const agentsQ = useAgents({ limit: 200 });
  const pending = useAssessments({ status: "classified" });
  const evals = useEvaluations();
  const events = useEvents({ limit: 500 });
  const o = ov.data;
  const agents = useMemo(() => agentsQ.data?.items ?? [], [agentsQ.data]);
  const by = (s: LifecycleStatus) => agents.filter((a) => a.lifecycle_status === s);
  const scored = agents.filter((a) => a.trust_score != null).sort((a, b) => (a.trust_score ?? 0) - (b.trust_score ?? 0));
  const meeting = scored.filter((a) => (a.trust_score ?? 0) >= BAR).length;
  const live = by("deployed").length + by("approved").length;
  const review = by("assessed").length + by("evaluated").length;
  const early = by("registered").length + by("onboarded").length;
  const blocked = by("suspended").length + by("retired").length;
  const viol = o?.policy_violations_24h ?? 0, checks = o?.guardrail_checks_24h ?? 0;
  const running = (evals.data ?? []).filter((e) => e.status === "running" || e.status === "queued");
  const nameOf = (id: string) => agents.find((a) => a.id === id)?.name ?? "Agent";
  const tiers = [1, 2, 3, 4].map((t) => ({ t, n: agents.filter((a) => a.risk_tier === t).length }));
  const [hot, setHot] = useState<number | null>(null);
  const assessed = tiers.reduce((a, x) => a + x.n, 0);

  // Governance events per day for the last 14 days, split by severity.
  const evDays = useMemo(() => {
    const days: { key: string; label: string; long: string; high: number; med: number; info: number }[] = [];
    const now = new Date();
    for (let i = 13; i >= 0; i--) { const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i); days.push({ key: d.toDateString(), label: dayFmt.format(d), long: longFmt.format(d), high: 0, med: 0, info: 0 }); }
    (events.data ?? []).forEach((e) => {
      const row = days.find((d) => d.key === new Date(e.created_at).toDateString()); if (!row) return;
      const s = e.severity.toLowerCase();
      if (["critical", "high", "error"].includes(s)) row.high++; else if (["medium", "warning"].includes(s)) row.med++; else row.info++;
    });
    return days;
  }, [events.data]);
  const evTotal = evDays.reduce((a, d) => a + d.high + d.med + d.info, 0);
  const evHigh = evDays.reduce((a, d) => a + d.high, 0);
  const evMed = evDays.reduce((a, d) => a + d.med, 0);

  // Red-team block rate by attack category across completed runs.
  const cats = useMemo(() => {
    const m: Record<string, { total: number; blocked: number }> = {};
    (evals.data ?? []).filter((e) => e.status === "completed").forEach((e) => Object.entries(e.summary.by_category ?? {}).forEach(([c, st]) => { m[c] = m[c] ?? { total: 0, blocked: 0 }; m[c].total += st.total; m[c].blocked += st.blocked; }));
    return Object.entries(m).map(([c, v]) => ({ c, rate: v.total ? (v.blocked / v.total) * 100 : 0, ...v })).sort((a, b) => a.rate - b.rate);
  }, [evals.data]);

  type Item = { key: string; sev: "high" | "med" | "low"; title: string; sub: string; href: string; cta: string };
  const todo: Item[] = [
    ...by("suspended").map((a) => ({ key: "s" + a.id, sev: "high" as const, title: `${a.name} is suspended`, sub: `Tier ${a.risk_tier ?? "—"} · trust ${a.trust_score ?? "—"}`, href: `/governance/agents/${a.id}`, cta: "Review" })),
    ...(pending.data ?? []).map((x) => ({ key: "d" + x.id, sev: "med" as const, title: `Risk decision · ${nameOf(x.agent_id)}`, sub: `Tier ${x.risk_tier} · submitted ${ago(x.submitted_at)}`, href: `/governance/risk/${x.id}`, cta: "Decide" })),
    ...agents.filter((a) => a.trust_score != null && a.trust_score < BAR && ["evaluated", "approved"].includes(a.lifecycle_status)).map((a) => ({ key: "t" + a.id, sev: "med" as const, title: `${a.name} below trust bar`, sub: `Trust ${a.trust_score?.toFixed(1)} of ${BAR}`, href: `/governance/agents/${a.id}`, cta: "Review" })),
    ...agents.filter((a) => a.lifecycle_status === "onboarded").map((a) => ({ key: "o" + a.id, sev: "low" as const, title: `${a.name} not assessed`, sub: "No risk tier yet", href: `/governance/agents/${a.id}`, cta: "Assess" })),
    ...running.map((e) => ({ key: "r" + e.id, sev: "low" as const, title: `Red-team running · ${nameOf(e.agent_id)}`, sub: `${e.progress} of ${e.prompts_total} prompts`, href: `/governance/evaluations/${e.id}`, cta: "View" })),
  ];

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
            vis={o?.average_trust_score != null ? <TrustMeter score={o.average_trust_score} /> : undefined}
            foot={`${meeting} of ${scored.length} tested agents meet the ${BAR} release bar`} />
          <Kpi icon={ShieldCheck} label="Guardrail checks · 24h" value={ov.isLoading ? <Skel w={60} h={22} /> : compact(checks)}
            vis={checks ? <CheckRing ok={viol / checks < 0.01} size={30} /> : undefined}
            foot={`${viol} blocked · ${checks ? (100 - (viol / checks) * 100).toFixed(2) : "100"}% passed`} />
          <Kpi icon={TriangleAlert} label="Open items" tone={todo.some((t) => t.sev === "high") ? "bad" : undefined} value={agentsQ.isLoading ? <Skel w={40} h={22} /> : String(todo.length)}
            foot={`${plural(o?.decisions_pending ?? 0, "decision", "decisions")} · ${plural(by("suspended").length, "suspended agent", "suspended agents")} · ${plural(running.length, "test running", "tests running")}`} />
        </section>
      )}

      <div className="gv-r1">
        <Card labelledBy="t-st">
          <CardHeader id="t-st" title="Agents by lifecycle stage" sub={`${agents.length} agents · registration to production`} action={<MoreLink href="/governance/agents">Registry</MoreLink>} />
          <div className="gv-chart">
            {agentsQ.isLoading ? <Skel h={230} /> : (
              <StackedBars height="fill" totals barMax={44} ariaLabel="Agents by lifecycle stage and risk tier" labels={STAGES.map((st) => LIFE_LABEL[st])}
                series={[
                  ...[1, 2, 3, 4].map((t) => ({ name: `Tier ${t} · ${TIER_LABEL[t]}`, color: TIER_COLOR[t], values: STAGES.map((st) => by(st).filter((x) => x.risk_tier === t).length) })),
                  { name: "Not assessed", color: "var(--line-2)", values: STAGES.map((st) => by(st).filter((x) => !x.risk_tier).length) },
                ]}
                fmt={(v) => String(v)} fmtAxis={(v) => String(Math.round(v))} />
            )}
          </div>
          <div className="gv-leg">{[1, 2, 3, 4].map((t) => <span key={t}><i style={{ background: TIER_COLOR[t] }} />Tier {t}</span>)}<span><i style={{ background: "var(--line-2)" }} />Not assessed</span></div>
        </Card>

        <Card labelledBy="t-tier">
          <CardHeader id="t-tier" title="Risk tiers" sub={`${assessed} assessed · ${agents.length - assessed} pending`} action={<MoreLink href="/governance/risk">Assessments</MoreLink>} />
          <div className="gv-donut">
            {agentsQ.isLoading ? <Skel w={150} h={150} /> : (
              <Ring size={148} stroke={20} gap={4} active={hot} onActive={setHot} ariaLabel={tiers.map((x) => `Tier ${x.t} ${x.n}`).join(", ")}
                slices={tiers.map((x) => ({ name: `Tier ${x.t} · ${TIER_LABEL[x.t]}`, value: x.n, color: TIER_COLOR[x.t] }))}
                center={hot != null
                  ? <span className="gv-dc"><b className="num">{tiers[hot].n}</b><span>Tier {tiers[hot].t}</span></span>
                  : <span className="gv-dc"><b className="num">{assessed}</b><span>assessed</span></span>} />
            )}
            <ul className="gv-tl">
              {[...tiers].reverse().map((x) => (
                <li key={x.t} className={hot != null && hot !== x.t - 1 ? "dim" : ""} onMouseEnter={() => setHot(x.t - 1)} onMouseLeave={() => setHot(null)}>
                  <div className="h"><i style={{ background: TIER_COLOR[x.t] }} aria-hidden /><span>Tier {x.t} <small>{TIER_LABEL[x.t]}</small></span><b className="num">{x.n}</b></div>
                  <span className="bar" aria-hidden><i style={{ width: `${assessed ? (x.n / assessed) * 100 : 0}%`, background: TIER_COLOR[x.t] }} /></span>
                </li>
              ))}
            </ul>
          </div>
        </Card>

        <Card labelledBy="t-trust">
          <CardHeader id="t-trust" title="Trust scores" sub={`Latest red-team score · release bar ${BAR}`} action={<MoreLink href="/governance/evaluations">Red-team</MoreLink>} />
          <div className="gv-hb">
            {agentsQ.isLoading ? <SkelRows rows={6} /> : !scored.length ? <Empty icon={ShieldCheck} title="No scores yet" /> : (
              <>
                <div className="gv-hb-rows">
                  {scored.map((a) => {
                    const v = a.trust_score as number, f = Math.max(0, (v - 50) / 50);
                    return (
                      <Link key={a.id} href={`/governance/agents/${a.id}`} className="gv-hb-row" title={`${a.name} · ${v.toFixed(1)}`}>
                        <span className="n">{a.name}</span>
                        <span className="gv-dp">
                          <i className="stem" style={{ width: `${f * 100}%` }} />
                          <i className="dot" style={{ left: `${f * 100}%`, background: pass(v) }} />
                        </span>
                        <b className="num">{v.toFixed(1)}</b>
                      </Link>
                    );
                  })}
                  <span className="gv-hb-line" style={{ ["--p" as string]: (BAR - 50) / 50 } as React.CSSProperties} aria-hidden><em>{BAR}</em></span>
                </div>
                <div className="gv-hb-axis" aria-hidden><span /><span className="t">{[50, 60, 70, 80, 90, 100].map((v) => <i key={v} style={{ left: `${((v - 50) / 50) * 100}%` }}>{v}</i>)}</span><span /></div>
              </>
            )}
          </div>
        </Card>
      </div>

      <div className="gv-r2">
        <Card labelledBy="t-ev">
          <CardHeader id="t-ev" title="Governance events" sub={`Last 14 days · ${evTotal} events · ${evHigh} high severity`} action={<MoreLink href="/governance/events">Audit log</MoreLink>} />
          <div className="gv-chart">
            {events.isError ? <ErrorState error={events.error} compact /> : events.isLoading ? <Skel h={220} /> : (
              <StackedBars height="fill" ariaLabel="Governance events per day by severity" labels={evDays.map((d) => d.label)} longs={evDays.map((d) => d.long)}
                barMax={30} series={[{ name: "Info", color: "var(--g1)", values: evDays.map((d) => d.info) }, { name: "Medium", color: "var(--g3)", values: evDays.map((d) => d.med) }, { name: "High", color: "var(--danger)", values: evDays.map((d) => d.high) }]}
                fmt={(v) => String(v)} fmtAxis={(v) => String(Math.round(v))} />
            )}
          </div>
          <div className="gv-leg">
            <span><i style={{ background: "var(--g1)" }} />Info <b className="num">{evTotal - evHigh - evMed}</b></span>
            <span><i style={{ background: "var(--g3)" }} />Medium <b className="num">{evMed}</b></span>
            <span><i style={{ background: "var(--danger)" }} />High <b className="num">{evHigh}</b></span>
          </div>
        </Card>

        <Card labelledBy="t-rt">
          <CardHeader id="t-rt" title="Red-team block rate" sub={`Attacks blocked by type · shaded gap to the ${BAR}% target`} action={<MoreLink href="/governance/evaluations">Runs</MoreLink>} />
          <div className="gv-hb">
            {evals.isLoading ? <SkelRows rows={6} /> : !cats.length ? <Empty icon={ShieldCheck} title="No completed runs" /> : (
              <div className="gv-hb-rows">
                {cats.map((c) => (
                  <div key={c.c} className="gv-hb-row" title={`${c.blocked} of ${c.total} attacks blocked`}>
                    <span className="n">{humanize(c.c)}</span>
                    <span className="gv-bb"><i style={{ width: `${c.rate}%` }} />{c.rate < BAR && <em style={{ left: `${c.rate}%`, width: `${BAR - c.rate}%` }} />}</span>
                    <b className="num">{c.rate.toFixed(0)}%</b>
                  </div>
                ))}
                <span className="gv-hb-line" style={{ ["--p" as string]: BAR / 100 } as React.CSSProperties} aria-hidden><em>{BAR}%</em></span>
              </div>
            )}
          </div>
        </Card>

        <Card labelledBy="t-todo">
          <CardHeader id="t-todo" title="Needs attention" sub={`${todo.length} open items`} bordered />
          <div className="scroll-y" style={{ flex: "1 1 0", minHeight: 0 }}>
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
      </div>
    </>
  );
}
