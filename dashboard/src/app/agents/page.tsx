"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Bot, Clock, Search, ShieldCheck, Wallet } from "lucide-react";
import { MiniBars, Ring, Segments } from "@/components/charts";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { Card, CardHeader, Delta, Empty, ErrorState, Kpi, PageHead, Seg, Skel, SkelRows } from "@/components/ui";
import { useObservedAgents, type ObservedAgent } from "@/lib/api";
import { ago, compact, ms, share, usd } from "@/lib/format";
import { rangePhrase, resolveTimeRange, timeRangeKey, type TimeRangeSpec } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

const ERR_LIMIT = 0.05;   // fraction
const SLOW_MS = 6000;
const IDLE_MIN = 60;
type Health = "errors" | "slow" | "idle" | "healthy";
const HEALTH: Record<Health, { label: string; tone: string }> = {
  errors: { label: "Errors", tone: "bad" }, slow: { label: "Slow", tone: "wait" }, idle: { label: "Idle", tone: "idle" }, healthy: { label: "Healthy", tone: "ok" },
};
function health(a: ObservedAgent, now: number): Health {
  if (a.error_rate > ERR_LIMIT) return "errors";
  if ((a.avg_duration_ms ?? 0) > SLOW_MS) return "slow";
  if (a.last_active && now - Date.parse(a.last_active) > IDLE_MIN * 60_000) return "idle";
  return "healthy";
}
type Filter = "all" | "attention" | "healthy";
type Sort = "spend" | "runs" | "errors" | "duration";

export default function AgentsPage() {
  const router = useRouter();
  const { spec, key } = useTimeRange();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("spend");
  const [now] = useState(() => Date.now());
  const range = useMemo(() => resolveTimeRange(spec), [spec]);
  const prevSpec = useMemo<TimeRangeSpec>(() => ({ kind: "custom", from: new Date(2 * range.from.getTime() - range.to.getTime()).toISOString(), to: range.from.toISOString() }), [range]);
  const { data, isLoading, isError, error, refetch } = useObservedAgents(spec, key);
  const prev = useObservedAgents(prevSpec, timeRangeKey(prevSpec));
  const items = useMemo(() => data?.items ?? [], [data]);

  const spend = items.reduce((a, x) => a + x.total_cost_usd, 0);
  const runs = items.reduce((a, x) => a + x.total_calls, 0);
  const failed = items.reduce((a, x) => a + x.error_rate * x.total_calls, 0);
  const errRate = runs ? failed / runs : 0;
  const avgMs = runs ? items.reduce((a, x) => a + (x.avg_duration_ms ?? 0) * x.total_calls, 0) / runs : 0;
  const prevSpend = prev.data ? prev.data.items.reduce((a, x) => a + x.total_cost_usd, 0) : null;
  const prevRuns = prev.data ? prev.data.items.reduce((a, x) => a + x.total_calls, 0) : null;
  const byHealth = useMemo(() => { const m: Record<Health, number> = { errors: 0, slow: 0, idle: 0, healthy: 0 }; items.forEach((a) => m[health(a, now)]++); return m; }, [items, now]);
  const projects = new Set(items.map((a) => a.project_id)).size;
  const ranked = [...items].sort((a, b) => b.total_cost_usd - a.total_cost_usd);
  const top3 = ranked.slice(0, 3);
  const slowest = [...items].sort((a, b) => (b.avg_duration_ms ?? 0) - (a.avg_duration_ms ?? 0));
  const maxMs = slowest[0]?.avg_duration_ms ?? 1;
  const attention = byHealth.errors + byHealth.slow;
  const SHADES = ["var(--s1)", "var(--s2)", "var(--s3)"];

  const list = items
    .filter((a) => `${a.name} ${a.project_name ?? ""} ${a.client_name ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .filter((a) => filter === "all" || (filter === "attention" ? ["errors", "slow"].includes(health(a, now)) : health(a, now) === "healthy"))
    .sort((a, b) => sort === "runs" ? b.total_calls - a.total_calls : sort === "errors" ? b.error_rate - a.error_rate : sort === "duration" ? (b.avg_duration_ms ?? 0) - (a.avg_duration_ms ?? 0) : b.total_cost_usd - a.total_cost_usd);
  const delta = (cur: number, before: number | null) => (before ? ((cur - before) / before) * 100 : null);

  return (
    <>
      <PageHead title="Agents" sub={`Every agent seen in telemetry over the ${rangePhrase(spec)}, with cost, speed and reliability.`} actions={<TimeRangePicker />} />

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Agent figures">
        <Kpi icon={Bot} label="Active agents" value={isLoading ? <Skel w={40} h={22} /> : compact(items.length)}
          vis={items.length ? <Ring size={34} stroke={5} ariaLabel="Agents by health" slices={[
            { name: "Healthy", value: byHealth.healthy, color: "var(--accent)" }, { name: "Slow", value: byHealth.slow, color: "var(--wait)" },
            { name: "Errors", value: byHealth.errors, color: "var(--danger)" }, { name: "Idle", value: byHealth.idle, color: "var(--line-2)" }]} /> : undefined}
          foot={<>{attention ? <b className="kpi-flag wait">{attention} need attention</b> : <b className="kpi-flag ok">All healthy</b>}&nbsp;· {projects} projects</>} />
        <Kpi icon={Wallet} label="Agent spend" value={isLoading ? <Skel w={100} h={22} /> : usd(spend)}
          vis={top3.length ? <div style={{ width: 88 }}><Segments ariaLabel="Spend by top agents" parts={[...top3.map((a, i) => ({ value: a.total_cost_usd, color: SHADES[i], label: a.name })), { value: Math.max(0, spend - top3.reduce((s, a) => s + a.total_cost_usd, 0)), color: "var(--line-2)", label: "Others" }]} /></div> : undefined}
          foot={delta(spend, prevSpend) != null ? <><Delta pct={delta(spend, prevSpend)!} />vs previous period</> : top3[0] ? `Top: ${top3[0].name}` : "—"} />
        <Kpi icon={ShieldCheck} label="Run error rate" tone={errRate > ERR_LIMIT ? "bad" : undefined}
          value={isLoading ? <Skel w={60} h={22} /> : <>{(errRate * 100).toFixed(2)}<small>%</small></>}
          vis={<ErrMeter rate={errRate} />}
          foot={`${compact(Math.round(failed))} failed of ${compact(runs)} runs`} />
        <Kpi icon={Clock} label="Avg. run time" value={isLoading ? <Skel w={60} h={22} /> : ms(avgMs)}
          vis={slowest.length ? <MiniBars values={[...slowest].reverse().map((a) => a.avg_duration_ms ?? 0)} width={80} height={30} /> : undefined}
          foot={slowest[0] ? <>Slowest&nbsp;<b style={{ color: "var(--text)", fontWeight: 600 }}>{slowest[0].name}</b>&nbsp;· {ms(slowest[0].avg_duration_ms)}</> : delta(runs, prevRuns) != null ? <><Delta pct={delta(runs, prevRuns)!} />runs</> : "—"} />
      </section>

      <Card labelledBy="t-ag">
        <CardHeader id="t-ag" title="All agents" sub={`${list.length} of ${items.length} · click a row to open its traces`}
          action={<div className="filterbar">
            <Seg small label="Show" value={filter} onChange={setFilter} options={[["all", `All ${items.length}`], ["attention", `Needs attention ${attention}`], ["healthy", `Healthy ${byHealth.healthy}`]] as const} />
            <label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Search agents</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search agents or projects" /></label>
          </div>} />
        <div style={{ marginTop: 12 }}>
          {isError ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading ? <SkelRows rows={8} /> : !list.length ? (
            <Empty icon={Bot} title={q || filter !== "all" ? "No agents match" : "No agent runs yet"}>
              {q || filter !== "all" ? "Try another name or filter." : "Agents show up when spans with kind “agent” arrive, for example from @trustai.agent in the SDK."}
            </Empty>
          ) : (
            <div className="scroll-x">
              <table className="ag-table">
                <thead><tr>
                  <th>Agent</th>
                  <th>Status</th>
                  <SortTh id="runs" sort={sort} setSort={setSort} className="r">Runs</SortTh>
                  <SortTh id="spend" sort={sort} setSort={setSort}>Spend</SortTh>
                  <SortTh id="duration" sort={sort} setSort={setSort}>Avg. run time</SortTh>
                  <SortTh id="errors" sort={sort} setSort={setSort}>Error rate</SortTh>
                  <th className="r">Last active</th>
                  <th aria-label="Open" />
                </tr></thead>
                <tbody>
                  {list.map((a) => {
                    const h = health(a, now);
                    const href = `/traces?agent=${encodeURIComponent(a.name)}${a.project_id ? `&project=${a.project_id}` : ""}`;
                    const fresh = a.last_active && now - Date.parse(a.last_active) < 5 * 60_000;
                    return (
                      <tr key={a.id} className="clickable" onClick={() => router.push(href)}>
                        <td>
                          <div className="cell-main">
                            <span className="ico" aria-hidden><Bot className="ic" /></span>
                            <div><b>{a.name}</b><small>{a.project_name ?? "Unassigned"}{a.client_name ? ` · ${a.client_name}` : ""}</small></div>
                          </div>
                        </td>
                        <td><span className={`ag-health ${HEALTH[h].tone}`}><i aria-hidden />{HEALTH[h].label}</span></td>
                        <td className="r"><b className="num">{compact(a.total_calls)}</b><div className="sub">{compact(a.total_tokens ?? 0)} tokens</div></td>
                        <td>
                          <div className="ag-metric">
                            <span className="ag-v"><b className="num">{usd(a.total_cost_usd)}</b><small>{share(spend ? a.total_cost_usd / spend : 0)}</small></span>
                            <span className="ag-bar"><i style={{ width: `${spend ? (a.total_cost_usd / (ranked[0]?.total_cost_usd || 1)) * 100 : 0}%`, background: "var(--accent)" }} /></span>
                          </div>
                        </td>
                        <td>
                          <div className="ag-metric">
                            <span className="ag-v"><b className="num" style={{ color: (a.avg_duration_ms ?? 0) > SLOW_MS ? "var(--wait)" : undefined }}>{ms(a.avg_duration_ms)}</b></span>
                            <span className="ag-bar"><i style={{ width: `${((a.avg_duration_ms ?? 0) / maxMs) * 100}%`, background: (a.avg_duration_ms ?? 0) > SLOW_MS ? "var(--wait)" : "var(--c5)" }} /></span>
                          </div>
                        </td>
                        <td>
                          <div className="ag-metric">
                            <span className="ag-v"><b className="num" style={{ color: a.error_rate > ERR_LIMIT ? "var(--danger)" : undefined }}>{(a.error_rate * 100).toFixed(2)}%</b><small>{compact(Math.round(a.error_rate * a.total_calls))} failed</small></span>
                            <span className="ag-bar err"><i style={{ width: `${Math.min(1, a.error_rate / (ERR_LIMIT * 2)) * 100}%`, background: a.error_rate > ERR_LIMIT ? "var(--danger)" : a.error_rate > ERR_LIMIT / 2 ? "var(--wait)" : "var(--accent)" }} /><em aria-hidden /></span>
                          </div>
                        </td>
                        <td className="r"><span className="ag-last">{fresh && <i className="live" aria-hidden />}{ago(a.last_active)}</span></td>
                        <td className="r"><Link href={href} className="ag-open" onClick={(e) => e.stopPropagation()} aria-label={`Traces for ${a.name}`}>Traces<ArrowUpRight className="ic" aria-hidden /></Link></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card-foot">
          <span className="ag-legend"><span><i className="ok" />Healthy</span><span><i className="wait" />Slow · over {SLOW_MS / 1000}s per run</span><span><i className="bad" />Errors · over {ERR_LIMIT * 100}% of runs</span><span><i className="idle" />Idle · no runs in {IDLE_MIN} min</span></span>
          <span>Error bars mark the {ERR_LIMIT * 100}% limit at the centre line</span>
        </div>
      </Card>
    </>
  );
}

function SortTh({ id, sort, setSort, className, children }: { id: Sort; sort: Sort; setSort: (s: Sort) => void; className?: string; children: React.ReactNode }) {
  return (
    <th className={className} aria-sort={sort === id ? "descending" : "none"}>
      <button type="button" className={`th-sort${sort === id ? " on" : ""}`} onClick={() => setSort(id)}>{children}<span aria-hidden>{sort === id ? "↓" : "↕"}</span></button>
    </th>
  );
}

/** Tiny meter: error rate against the 5% limit (tick at the limit). */
function ErrMeter({ rate }: { rate: number }) {
  const f = Math.min(1, rate / (ERR_LIMIT * 2));
  const c = rate > ERR_LIMIT ? "var(--danger)" : rate > ERR_LIMIT / 2 ? "var(--wait)" : "var(--accent)";
  return (
    <svg width={88} height={30} viewBox="0 0 88 30" aria-hidden>
      <rect x={0} y={13} width={88} height={6} rx={3} fill="var(--hover)" />
      <rect x={0} y={13} width={Math.max(3, f * 88)} height={6} rx={3} fill={c} />
      <line x1={44} x2={44} y1={8} y2={24} stroke="var(--text-3)" strokeWidth={1.5} strokeLinecap="round" />
      <text x={44} y={6} textAnchor="middle" className="ax" style={{ fontSize: 8.5 }}>5%</text>
    </svg>
  );
}
