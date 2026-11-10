"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, ClipboardCheck, Library, ShieldCheck, TriangleAlert } from "lucide-react";
import { CheckRing, RangeTrend, Ring, Sparkline, StackedBars } from "@/components/charts";
import { LIFE_LABEL, TIER_LABEL } from "@/components/gov";
import { Card, CardHeader, Empty, ErrorState, Kpi, MoreLink, PageHead, Skel, SkelRows } from "@/components/ui";
import { useAgents, useAssessments, useEvaluations, useEvents, useOverview, type LifecycleStatus } from "@/lib/governance";
import { ago, compact, humanize } from "@/lib/format";

const BAR = 95;
// Risk tiers use the brand's evergreen ramp (light → dark = low → high); red is kept for the critical tier only.
const TIER_COLOR: Record<number, string> = { 1: "var(--g1)", 2: "var(--g2)", 3: "var(--g3)", 4: "var(--danger)" };
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const longFmt = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });

/** Small KPI meter with a tick at the 95 release bar. */
function TrustMeter({ score }: { score: number }) {
  const f = Math.max(0, Math.min(1, (score - 50) / 50));
  const c = score >= BAR ? "var(--accent)" : "var(--wait)";
  return <span className="gv-track" style={{ width: 88 }} aria-hidden><i style={{ width: `${f * 100}%`, background: c }} /><em style={{ left: `${((BAR - 50) / 50) * 100}%` }} /></span>;
}

/** Change indicator: green up, red down. */
function Delta({ v, small }: { v: number; small?: boolean }) {
  const up = v >= 0, Icon = up ? ArrowUpRight : ArrowDownRight;
  return <span className={`gv-delta ${up ? "up" : "down"}${small ? " sm" : ""}`}><Icon aria-hidden />{Math.abs(v).toFixed(1)}</span>;
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

  const done = useMemo(() => (evals.data ?? []).filter((e) => e.status === "completed" && e.trust_score != null)
    .sort((a, b) => +new Date(b.finished_at ?? b.created_at) - +new Date(a.finished_at ?? a.created_at)), [evals.data]);
  const latest = useMemo(() => { const seen = new Set<string>(); return done.filter((e) => (seen.has(e.agent_id) ? false : (seen.add(e.agent_id), true))); }, [done]);

  // Weekly trust picture: each agent's latest score as of each week's end.
  const WEEKS = 8;
  const [now] = useState(() => Date.now());
  const trend = useMemo(() => {
    const DAY = 864e5;
    const ends = Array.from({ length: WEEKS }, (_, k) => now - (WEEKS - 1 - k) * 7 * DAY);
    const perAgent: Record<string, number[]> = {};
    const pts = ends.map((end) => {
      const seen = new Set<string>(); const vals: number[] = [];
      done.forEach((e) => { if (seen.has(e.agent_id) || +new Date(e.finished_at ?? e.created_at) > end) return; seen.add(e.agent_id); vals.push(e.trust_score as number); });
      return vals;
    });
    latest.forEach((l) => { perAgent[l.agent_id] = ends.map((end) => done.find((e) => e.agent_id === l.agent_id && +new Date(e.finished_at ?? e.created_at) <= end)?.trust_score ?? NaN); });
    return {
      labels: ends.map((t, k) => (k === WEEKS - 1 ? "Now" : dayFmt.format(new Date(t)))),
      longs: ends.map((t, k) => (k === WEEKS - 1 ? "This week" : `Week to ${dayFmt.format(new Date(t))}`)),
      avg: pts.map((v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : NaN)),
      lo: pts.map((v) => (v.length ? Math.min(...v) : NaN)), hi: pts.map((v) => (v.length ? Math.max(...v) : NaN)),
      passing: pts.map((v) => v.filter((x) => x >= BAR).length), counts: pts.map((v) => v.length), perAgent,
    };
  }, [done, latest, now]);
  const rank = latest.map((e) => {
    const a = agents.find((x) => x.id === e.agent_id);
    const prev = done.find((x) => x.agent_id === e.agent_id && x.id !== e.id);
    return { id: e.agent_id, name: a?.name ?? "Agent", tier: a?.risk_tier, stage: a?.lifecycle_status, score: e.trust_score as number, delta: prev ? (e.trust_score as number) - (prev.trust_score as number) : null, hist: (trend.perAgent[e.agent_id] ?? []).filter((v) => !Number.isNaN(v)) };
  }).sort((a, b) => a.score - b.score);
  const avgNow = trend.avg[WEEKS - 1], avgThen = trend.avg.find((v) => !Number.isNaN(v));
  const blockedAll = latest.reduce((acc, e) => { Object.values(e.summary.by_category ?? {}).forEach((st) => { acc.t += st.total; acc.b += st.blocked; }); return acc; }, { t: 0, b: 0 });

  // Red-team block rate by attack category, latest run per agent.
  const cats = useMemo(() => {
    const m: Record<string, { total: number; blocked: number }> = {};
    latest.forEach((e) => Object.entries(e.summary.by_category ?? {}).forEach(([c, st]) => { m[c] = m[c] ?? { total: 0, blocked: 0 }; m[c].total += st.total; m[c].blocked += st.blocked; }));
    return Object.entries(m).map(([c, v]) => ({ c, rate: v.total ? (v.blocked / v.total) * 100 : 0, ...v })).sort((a, b) => a.rate - b.rate);
  }, [latest]);

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
        <Card labelledBy="t-trust">
          <CardHeader id="t-trust" title="Trust score" action={<MoreLink href="/governance/evaluations">Red-team runs</MoreLink>} />
          <div className="gv-trust">
            <div className="gv-tc">
              <div className="gv-hl">
                <b className="num">{Number.isFinite(avgNow) ? avgNow.toFixed(1) : "—"}</b>
                {avgThen != null && Number.isFinite(avgNow) && <Delta v={avgNow - avgThen} />}
                <span>average of {latest.length} tested agents · {WEEKS} weeks</span>
              </div>
              <div className="gv-chart">
                {evals.isLoading ? <Skel h={220} /> : (
                  <RangeTrend ariaLabel="Average trust score per week with highest and lowest agent" labels={trend.labels} longs={trend.longs}
                    avg={trend.avg} lo={trend.lo} hi={trend.hi} refValue={BAR} refLabel={`Release bar ${BAR}`} yMin={60} yMax={100} fmt={(v) => v.toFixed(1)}
                    extra={trend.passing.map((p, k) => [{ name: "At or above bar", value: `${p} of ${trend.counts[k]}` }])} />
                )}
              </div>
              <div className="gv-key">
                <span><i className="ln" />Average</span><span><i className="rg" />Range, lowest to highest agent</span><span><i className="rf" />Release bar</span>
              </div>
            </div>
            <div className="gv-rank">
              <div className="gv-rank-h"><span>By agent · weakest first</span><span>Latest</span></div>
              {evals.isLoading ? <SkelRows rows={6} /> : rank.map((r) => (
                <Link key={r.id} href={`/governance/agents/${r.id}`} className="gv-rank-row">
                  <span className="who"><b>{r.name}</b><small>{r.tier ? `Tier ${r.tier}` : "No tier"} · {r.stage ? LIFE_LABEL[r.stage] : ""}</small></span>
                  <span className="spk"><Sparkline values={r.hist} width={64} height={22} color={r.score >= BAR ? "var(--accent)" : "var(--danger)"} /></span>
                  <span className="sc"><b className="num">{r.score.toFixed(1)}</b>{r.delta != null ? <Delta v={r.delta} small /> : <small className="muted">new</small>}</span>
                </Link>
              ))}
            </div>
          </div>
        </Card>

        <Card labelledBy="t-risk">
          <CardHeader id="t-risk" title="Risk posture" action={<MoreLink href="/governance/risk">Assessments</MoreLink>} />
          <div className="gv-pad">
            <div className="gv-hl"><b className="num">{assessed}</b><span>of {agents.length} agents risk-assessed</span></div>
            {agentsQ.isLoading ? <Skel h={14} /> : (
              <div className="gv-stack" role="img" aria-label={tiers.map((x) => `Tier ${x.t}: ${x.n}`).join(", ")}>
                {[...tiers].reverse().filter((x) => x.n).map((x) => <i key={x.t} style={{ flexGrow: x.n, background: TIER_COLOR[x.t] }} title={`Tier ${x.t} · ${x.n}`} />)}
                {agents.length - assessed > 0 && <i className="na" style={{ flexGrow: agents.length - assessed }} title={`Not assessed · ${agents.length - assessed}`} />}
              </div>
            )}
            <ul className="gv-tiers">
              {[...tiers].reverse().map((x) => {
                const names = agents.filter((a) => a.risk_tier === x.t).map((a) => a.name);
                return (
                  <li key={x.t}>
                    <i style={{ background: TIER_COLOR[x.t] }} aria-hidden />
                    <span className="t"><b>Tier {x.t}</b><small>{TIER_LABEL[x.t]}</small></span>
                    <span className="nm" title={names.join(", ")}>{names.join(", ") || "—"}</span>
                    <b className="num">{x.n}</b>
                  </li>
                );
              })}
              <li className="na">
                <i aria-hidden />
                <span className="t"><b>Not assessed</b></span>
                <span className="nm">{agents.filter((a) => !a.risk_tier).map((a) => a.name).join(", ") || "—"}</span>
                <b className="num">{agents.length - assessed}</b>
              </li>
            </ul>
          </div>
        </Card>
      </div>

      <div className="gv-r2">
        <Card labelledBy="t-ev">
          <CardHeader id="t-ev" title="Governance activity" action={<MoreLink href="/governance/events">Audit log</MoreLink>} />
          <div className="gv-hl gv-pad0">
            <b className="num">{evTotal}</b><span>events · last 14 days</span>
            <span className="gv-inl"><span><i style={{ background: "var(--g1)" }} />Info</span><span><i style={{ background: "var(--g3)" }} />Medium</span><span><i style={{ background: "var(--danger)" }} />High · {evHigh}</span></span>
          </div>
          <div className="gv-chart">
            {events.isError ? <ErrorState error={events.error} compact /> : events.isLoading ? <Skel h={200} /> : (
              <StackedBars height="fill" barMax={14} ariaLabel="Governance events per day by severity" labels={evDays.map((d) => d.label)} longs={evDays.map((d) => d.long)}
                series={[{ name: "Info", color: "var(--g1)", values: evDays.map((d) => d.info) }, { name: "Medium", color: "var(--g3)", values: evDays.map((d) => d.med) }, { name: "High", color: "var(--danger)", values: evDays.map((d) => d.high) }]}
                fmt={(v) => String(v)} fmtAxis={(v) => String(Math.round(v))} />
            )}
          </div>
        </Card>

        <Card labelledBy="t-rt">
          <CardHeader id="t-rt" title="Red-team results by attack type" action={<MoreLink href="/governance/evaluations">Runs</MoreLink>} />
          <div className="gv-hl gv-pad0">
            <b className="num">{blockedAll.t ? ((blockedAll.b / blockedAll.t) * 100).toFixed(1) : "—"}%</b><span>of attacks blocked · target {BAR}%</span>
          </div>
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
          <CardHeader id="t-todo" title="Needs attention" />
          <div className="gv-hl gv-pad0"><b className="num">{todo.length}</b><span>open items</span></div>
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
