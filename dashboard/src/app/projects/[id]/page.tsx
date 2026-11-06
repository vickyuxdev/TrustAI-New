"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowUpRight, Bot, Clock, GitBranch, Pencil, ShieldCheck, Wallet, Zap } from "lucide-react";
import { ApiKeysCard } from "@/components/ApiKeys";
import { SpanFeed } from "@/components/blocks";
import { BarChart, CheckRing, Gauge, MiniBars, SERIES, Segments, Sparkline } from "@/components/charts";
import { ProjectForm, CAPTURE_LABEL } from "@/components/ProjectForm";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { Card, CardHeader, CopyButton, Delta, Empty, ErrorState, Kpi, MoreLink, Seg, ShareCell, Skel, SkelRows, StatStrip } from "@/components/ui";
import { useClients, useCostBreakdown, useProject, useProjectAgents, useTraces, type Dim } from "@/lib/api";
import { ago, compact, day, envName, ms, pct, providerName, share, usd, usdShort } from "@/lib/format";
import { projectIcon } from "@/lib/projectIcon";
import { fillDays } from "@/lib/series";
import { describeTimeRange, rangePhrase, resolveTimeRange, timeRangeKey, type TimeRangeSpec } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

const DAY = 86_400_000;
type Metric = "cost" | "calls" | "tokens";
const ingestUrl = process.env.NEXT_PUBLIC_INGESTION_URL || "http://localhost:8001";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const { spec, key } = useTimeRange();
  const [edit, setEdit] = useState(false);
  const [metric, setMetric] = useState<Metric>("cost");
  const range = useMemo(() => resolveTimeRange(spec), [spec]);
  const periodDays = Math.max(1, Math.round((range.to.getTime() - range.from.getTime()) / DAY));
  const prevSpec = useMemo<TimeRangeSpec>(() => ({ kind: "custom", from: new Date(range.from.getTime() - (range.to.getTime() - range.from.getTime())).toISOString(), to: range.from.toISOString() }), [range]);
  const monthSpec = useMemo<TimeRangeSpec>(() => { const n = new Date(); return { kind: "custom", from: new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), 1)).toISOString(), to: n.toISOString() }; }, []);

  const project = useProject(id, 30);
  const clients = useClients(30);
  const cost = useCostBreakdown(spec, key, { project_id: id });
  const prev = useCostBreakdown(prevSpec, timeRangeKey(prevSpec), { project_id: id });
  const month = useCostBreakdown(monthSpec, timeRangeKey(monthSpec), { project_id: id });
  const agents = useProjectAgents(id, periodDays);
  const traces = useTraces(spec, key, { project_id: id, page_size: 30 }, { refetchInterval: 20_000 });

  const days = useMemo(() => fillDays(cost.data?.time_series ?? [], range.from, range.to), [cost.data, range]);
  const p = project.data;
  const sumOf = (rows: Dim[] | undefined, k: "total_cost_usd" | "total_calls" | "total_tokens") => (rows ?? []).reduce((a, d) => a + d[k], 0);
  const total = sumOf(cost.data?.by_model, "total_cost_usd");
  const calls = sumOf(cost.data?.by_model, "total_calls");
  const tokens = sumOf(cost.data?.by_model, "total_tokens");
  const prevTotal = prev.data ? prev.data.time_series.reduce((a, d) => a + d.total_cost_usd, 0) : null;
  const prevCalls = prev.data ? prev.data.time_series.reduce((a, d) => a + d.total_calls, 0) : null;
  const delta = (cur: number, before: number | null) => (before ? ((cur - before) / before) * 100 : null);
  const ag = agents.data?.items ?? [];
  const agCalls = ag.reduce((a, x) => a + x.total_calls, 0);
  const errRate = agCalls ? ag.reduce((a, x) => a + x.error_rate * x.total_calls, 0) / agCalls : 0;
  const avgRun = agCalls ? ag.reduce((a, x) => a + (x.avg_duration_ms ?? 0) * x.total_calls, 0) / agCalls : 0;
  const slowest = [...ag].sort((a, b) => (b.avg_duration_ms ?? 0) - (a.avg_duration_ms ?? 0))[0];
  const agSpend = ag.reduce((a, x) => a + x.total_cost_usd, 0);
  const peak = days.reduce<typeof days[number] | null>((m, d) => (d[metric] > (m?.[metric] ?? 0) ? d : m), null);
  const client = clients.data?.items.find((c) => c.id === p?.client_id);
  const live = (traces.data?.items.length ?? 0) > 0;

  if (project.isError) return <Card><ErrorState error={project.error} onRetry={() => project.refetch()} /></Card>;

  const metricVal = (v: number) => (metric === "cost" ? usd(v) : compact(v));
  const metricTotal = metric === "cost" ? total : metric === "calls" ? calls : tokens;

  return (
    <>
      {/* ── Header ── */}
      <header className="pd-hero">
        <span className="pd-icon" aria-hidden>{p ? projectIcon(p.name, p.description ?? "") : null}</span>
        <div className="pd-title">
          <div className="pd-name">
            <h1>{p ? p.name : <Skel w={220} h={24} />}</h1>
            {p && <span className={`pj-status${live ? "" : " idle"}`}><i aria-hidden />{live ? "Monitored" : "Idle"}</span>}
          </div>
          <p>{p?.description ?? " "}</p>
          <ul className="pd-meta">
            <li><span>Client</span><b>{client?.name ?? "—"}</b></li>
            <li><span>Content capture</span><b>{p ? CAPTURE_LABEL[p.content_capture_mode] : "—"}</b></li>
            <li><span>Created</span><b>{p ? day(p.created_at) : "—"}</b></li>
            <li><span>Project ID</span><b className="mono">{p ? `${p.id.slice(0, 8)}…` : "—"}</b>{p && <CopyButton text={p.id} label="Copy" />}</li>
          </ul>
        </div>
        <div className="pd-actions">
          <TimeRangePicker />
          <Link href={`/traces?project=${id}`} className="btn"><GitBranch className="ic" aria-hidden />Traces</Link>
          <button type="button" className="btn btn-primary" onClick={() => setEdit(true)} disabled={!p}><Pencil className="ic" aria-hidden />Edit project</button>
        </div>
      </header>

      {/* ── KPIs (all for the selected period) ── */}
      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Project figures">
        <Kpi icon={Wallet} label="Spend" value={cost.isLoading ? <Skel w={90} h={22} /> : usd(total)} vis={<Sparkline values={days.map((d) => d.cost)} width={88} height={30} />}
          foot={delta(total, prevTotal) != null ? <><Delta pct={delta(total, prevTotal)!} />vs previous {periodDays} days</> : describeTimeRange(spec)} />
        <Kpi icon={Zap} label="AI calls" value={cost.isLoading ? <Skel w={70} h={22} /> : compact(calls)} vis={<MiniBars values={days.slice(-12).map((d) => d.calls)} width={72} height={30} />}
          foot={<>{delta(calls, prevCalls) != null && <Delta pct={delta(calls, prevCalls)!} />}{calls ? `${usd(total / calls)} per call` : "No calls"}</>} />
        <Kpi icon={ShieldCheck} label="Error rate" tone={errRate > 5 ? "bad" : undefined} value={agents.isLoading ? <Skel w={60} h={22} /> : <>{errRate.toFixed(2)}<small>%</small></>}
          vis={<CheckRing ok={errRate <= 5} size={30} />} foot={agCalls ? `${compact(Math.round((errRate / 100) * agCalls))} failed agent runs` : "No agent runs yet"} />
        <Kpi icon={Clock} label="Avg. agent run time" value={agents.isLoading ? <Skel w={60} h={22} /> : ms(avgRun)}
          foot={slowest ? <>Slowest: <b style={{ color: "var(--text)", fontWeight: 600, marginLeft: 4 }}>{slowest.name}</b>&nbsp;· {ms(slowest.avg_duration_ms)}</> : "—"} />
      </section>

      {/* ── Trend + budget ── */}
      <div className="split-l">
        <Card labelledBy="t-tr">
          <CardHeader id="t-tr" title={metric === "cost" ? "Spend over time" : metric === "calls" ? "AI calls over time" : "Tokens over time"} sub={`Per day · ${describeTimeRange(spec)}`}
            action={<Seg small label="Metric" value={metric} onChange={setMetric} options={[["cost", "Spend"], ["calls", "Calls"], ["tokens", "Tokens"]] as const} />} />
          <div style={{ padding: "14px 18px 0" }}>
            <StatStrip items={[
              ["Total", metricVal(metricTotal)],
              ["Average per day", metricVal(days.length ? metricTotal / days.length : 0)],
              ["Peak day", peak ? `${peak.label} · ${metricVal(peak[metric])}` : "—"],
              ["Main model", cost.data?.by_model[0]?.dimension ?? "—"],
            ]} />
          </div>
          <div style={{ flex: 1, minHeight: 230, margin: "16px 18px 16px" }}>
            {cost.isLoading ? <Skel h={230} /> : (
              <BarChart height="fill" valueLabels={false} emphasis="max" ariaLabel={`${metric} per day`}
                data={days.map((d) => ({ label: d.label, long: d.long, value: d[metric], extra: metric === "cost" ? [{ name: "AI calls", value: compact(d.calls) }, { name: "Tokens", value: compact(d.tokens) }] : [{ name: "Spend", value: usd(d.cost) }] }))}
                fmt={metricVal} fmtAxis={(v) => (metric === "cost" ? usdShort(v) : compact(v))} />
            )}
          </div>
        </Card>
        <BudgetCard budget={p?.monthly_budget_usd ?? null} mtd={month.data ? month.data.time_series.reduce((a, d) => a + d.total_cost_usd, 0) : null}
          models={cost.data?.by_model ?? []} envs={cost.data?.by_environment ?? []} providers={cost.data?.by_provider ?? []} total={total} loading={month.isLoading || cost.isLoading} onEdit={() => setEdit(true)} />
      </div>

      {/* ── Agents + activity ── */}
      <div className="split-wide">
        <Card labelledBy="t-ag" style={{ height: 380 }}>
          <CardHeader id="t-ag" title="Agents" sub={`${ag.length} agents · ${rangePhrase(spec)}`} action={<MoreLink href="/agents">All agents</MoreLink>} />
          <div className="scroll-y sticky-head" style={{ flex: 1, minHeight: 0, marginTop: 12 }}>
            {agents.isError ? <ErrorState error={agents.error} compact /> : agents.isLoading ? <SkelRows rows={4} /> : !ag.length ? (
              <Empty icon={Bot} title="No agents yet">Agents appear here once the SDK reports an agent span for this project.</Empty>
            ) : (
              <table>
                <thead><tr><th>Agent</th><th>Share of spend</th><th className="r">Spend</th><th className="r">Calls</th><th className="r">Avg. run time</th><th>Error rate</th><th className="r">Last active</th><th /></tr></thead>
                <tbody>
                  {ag.map((a, i) => (
                    <tr key={a.id}>
                      <td><div className="cell-main"><span className="ico" aria-hidden><Bot className="ic" /></span><div><b>{a.name}</b><small>{compact(a.total_tokens ?? 0)} tokens</small></div></div></td>
                      <td style={{ minWidth: 150 }}>
                        <ShareCell fraction={agSpend ? a.total_cost_usd / agSpend : 0} color={SERIES[i % SERIES.length]} label={share(agSpend ? a.total_cost_usd / agSpend : 0)} />
                      </td>
                      <td className="r strong">{usd(a.total_cost_usd)}</td>
                      <td className="r">{compact(a.total_calls)}</td>
                      <td className="r">{ms(a.avg_duration_ms)}</td>
                      <td><span className={`sdot ${a.error_rate > 5 ? "bad" : "ok"}`}><i aria-hidden />{pct(a.error_rate, a.error_rate ? 2 : 0)}</span></td>
                      <td className="r muted">{a.last_active ? ago(a.last_active) : "—"}</td>
                      <td className="r"><Link href={`/traces?project=${id}&agent=${encodeURIComponent(a.name)}`} className="pd-link" aria-label={`Traces for ${a.name}`}>Traces<ArrowUpRight className="ic" aria-hidden /></Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
        <Card labelledBy="t-live" style={{ height: 380 }}>
          <CardHeader id="t-live" title="Live activity" bordered sub={traces.data ? `${compact(traces.data.total)} spans · ${rangePhrase(spec)}` : "Recent spans"} action={<span className="pill pill-accent"><i className="live" aria-hidden />Live</span>} />
          {traces.isError ? <div className="card-b"><ErrorState error={traces.error} compact /></div> : traces.isLoading ? <SkelRows rows={5} /> : <SpanFeed spans={traces.data?.items ?? []} />}
          <div className="card-foot"><span>Most recent first · updates every 20s</span><MoreLink href={`/traces?project=${id}`}>Open in traces</MoreLink></div>
        </Card>
      </div>

      {/* ── Keys + setup ── */}
      <div className="split-l" style={{ alignItems: "start" }}>
        <ApiKeysCard projectId={id} />
        <Card labelledBy="t-setup">
          <CardHeader id="t-setup" title="Connect the SDK" sub="Two lines in your agent code start sending telemetry" bordered action={<MoreLink href="/settings/onboarding">Setup guide</MoreLink>} />
          <div className="card-b">
            <pre className="code" style={{ margin: 0 }}>{`import trustai

trustai.init(
    api_key="tai_live_…",
    project_id="${p?.id ?? "…"}",
    ingest_url="${ingestUrl}",
)`}</pre>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="small muted">Use a key from the list. Content is captured as: <b style={{ color: "var(--text)", fontWeight: 600 }}>{p ? CAPTURE_LABEL[p.content_capture_mode] : "—"}</b></span>
              {p && <CopyButton text={`import trustai\n\ntrustai.init(\n    api_key="YOUR_KEY",\n    project_id="${p.id}",\n    ingest_url="${ingestUrl}",\n)`} label="Copy snippet" />}
            </div>
          </div>
        </Card>
      </div>

      {p && <ProjectForm open={edit} onClose={() => setEdit(false)} project={p} />}
    </>
  );
}

function BudgetCard({ budget, mtd, models, envs, providers, total, loading, onEdit }: {
  budget: number | null; mtd: number | null; models: Dim[]; envs: Dim[]; providers: Dim[]; total: number; loading: boolean; onEdit: () => void;
}) {
  const now = new Date();
  const dim = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0)).getUTCDate();
  const elapsed = Math.max(1, now.getUTCDate() - 1 + now.getUTCHours() / 24);
  const left = Math.max(0, dim - elapsed);
  const runRate = mtd != null ? mtd / elapsed : 0;
  const projected = mtd != null ? runRate * dim : null;
  const monthName = now.toLocaleString("en-US", { month: "long", timeZone: "UTC" });
  const used = budget && mtd != null ? mtd / budget : 0;
  const over = budget && projected != null && projected > budget;
  const topModels = models.filter((m) => m.total_cost_usd > 0).slice(0, 4);
  const rest = total - topModels.reduce((a, m) => a + m.total_cost_usd, 0);

  return (
    <Card labelledBy="t-bud">
      <CardHeader id="t-bud" title={`${monthName} budget`} sub={budget ? `${usd(budget)} per month` : "No monthly budget set"} action={<button type="button" className="btn btn-sm" onClick={onEdit}>{budget ? "Change" : "Set budget"}</button>} />
      <div className="card-b pd-budget">
        {loading ? <Skel h={120} /> : budget ? (
          <div className="pd-gauge">
            <Gauge used={used} projected={projected != null ? projected / budget : null}
              center={<><b className="num">{Math.round(used * 100)}%</b><span>used</span></>} />
            <div className="pd-gauge-txt">
              <div className="pd-mtd"><b className="num">{usd(mtd ?? 0)}</b><span>of {usd(budget)} spent so far</span></div>
              <div className={`pd-forecast${over ? " bad" : ""}`}>
                {over ? <>On pace for <b>{usd(projected!)}</b> — about <b>{usd(projected! - budget)}</b> over by {monthName} {dim}.</>
                  : <>On pace for <b>{usd(projected ?? 0)}</b> by {monthName} {dim} — within budget.</>}
              </div>
            </div>
            <dl className="pd-mini">
              <div><dt>Spending now</dt><dd>{usd(runRate)}<small>/day</small></dd></div>
              <div><dt>Can spend</dt><dd>{left ? usd(Math.max(0, budget - (mtd ?? 0)) / left) : "—"}<small>/day</small></dd></div>
              <div><dt>Days left</dt><dd>{Math.ceil(left)}<small> of {dim}</small></dd></div>
            </dl>
          </div>
        ) : (
          <div className="pd-nobudget"><Wallet className="ic" aria-hidden /><span>Set a monthly budget to see how this month is tracking and get a forecast for month-end.</span></div>
        )}

        <section className="pd-mix">
          <h3>Spend by model</h3>
          {loading ? <SkelRows rows={3} /> : !topModels.length ? <p className="small muted">No model spend in this period.</p> : (
            <ul>
              {[...topModels.map((m, i) => ({ name: m.dimension, v: m.total_cost_usd, c: SERIES[i] })), ...(rest > 0.005 ? [{ name: "Other", v: rest, c: "var(--c5)" }] : [])].map((m) => (
                <li key={m.name}>
                  <i style={{ background: m.c }} aria-hidden />
                  <span className="n" title={m.name}>{m.name}</span>
                  <span className="bar-track" aria-hidden><i style={{ width: `${total ? (m.v / total) * 100 : 0}%`, background: m.c }} /></span>
                  <b className="num">{share(total ? m.v / total : 0)}</b>
                  <span className="v num">{usd(m.v)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="pd-split">
          <div>
            <h3>Environment</h3>
            <Segments ariaLabel="Spend by environment" parts={envs.map((e, i) => ({ value: e.total_cost_usd, color: ["var(--s1)", "var(--s2)", "var(--s3)"][i] ?? "var(--c5)", label: envName(e.dimension) }))} />
            <ul className="seg-legend">{envs.map((e, i) => <li key={e.dimension}><i style={{ background: ["var(--s1)", "var(--s2)", "var(--s3)"][i] ?? "var(--c5)" }} />{envName(e.dimension)} <b>{share(total ? e.total_cost_usd / total : 0)}</b></li>)}</ul>
          </div>
          <div>
            <h3>Provider</h3>
            <Segments ariaLabel="Spend by provider" parts={providers.map((e, i) => ({ value: e.total_cost_usd, color: SERIES[i] ?? "var(--c5)", label: providerName(e.dimension) }))} />
            <ul className="seg-legend">{providers.map((e, i) => <li key={e.dimension}><i style={{ background: SERIES[i] ?? "var(--c5)" }} />{providerName(e.dimension)} <b>{share(total ? e.total_cost_usd / total : 0)}</b></li>)}</ul>
          </div>
        </section>
      </div>
    </Card>
  );
}
