"use client";
import { useMemo, useState } from "react";
import { ArrowUpRight, Bot, ChevronLeft, ChevronRight, Clock, GitBranch, Pause, Play, Search, ShieldCheck, Sparkles, Wallet, Wrench, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { TraceDrawer } from "@/components/TraceDrawer";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { MiniBars, Sparkline } from "@/components/charts";
import { Card, ChipSelect, Duo, Empty, ErrorState, Kpi, PageHead, Seg, Skel, SkelRows } from "@/components/ui";
import { useConnectors, useCostBreakdown, useOverviewMetrics, useProjects, useTraces, type Span } from "@/lib/api";
import { ago, clock, compact, envName, ms, providerName, usd } from "@/lib/format";
import { fillDays } from "@/lib/series";
import { projectLabels } from "@/lib/projects";
import { describeTimeRange, rangePhrase, resolveTimeRange } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

const PAGE = 15;
const ERR_LIMIT = 5; // %
const SLOW_MS = 5000;
type Kind = "all" | "agent" | "llm" | "tool";
const KIND_ICON = { agent: Bot, llm: Sparkles, tool: Wrench } as const;
const KIND_LABEL: Record<string, string> = { agent: "Agent", llm: "LLM call", tool: "Tool" };
const BUCKETS: [number, string][] = [[250, "<250ms"], [500, "250–500ms"], [1000, "0.5–1s"], [2000, "1–2s"], [4000, "2–4s"], [Infinity, "4s+"]];
function KindIcon({ kind }: { kind: string }) {
  const k = (kind in KIND_ICON ? kind : "llm") as keyof typeof KIND_ICON;
  return <span className={`tr-kind ${k}`} aria-hidden>{k === "agent" ? <Bot className="ic" /> : k === "tool" ? <Wrench className="ic" /> : <Sparkles className="ic" />}</span>;
}
const spanTitle = (s: Span) => (s.span_name.includes(":") ? s.span_name.split(":").slice(1).join(":") : s.span_name);

export default function TracesPage() {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const { spec, key } = useTimeRange();
  const project = params.get("project") ?? "";
  const agent = params.get("agent") ?? "";
  const traceParam = params.get("trace");
  const [q, setQ] = useState(params.get("q") ?? "");
  const [env, setEnv] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [page, setPage] = useState(1);
  const [live, setLive] = useState(true);
  const [open, setOpen] = useState<string | null>(traceParam);
  const [kind, setKind] = useState<Kind>("all");

  // Keep local state in step with the URL / filters (adjusting state during render, not in effects).
  const qParam = params.get("q") ?? "";
  const filterSig = [project, agent, env, model, status, source, key].join("|");
  const [prev, setPrev] = useState({ traceParam, qParam, filterSig });
  if (prev.traceParam !== traceParam || prev.qParam !== qParam || prev.filterSig !== filterSig) {
    if (prev.traceParam !== traceParam) setOpen(traceParam);
    if (prev.qParam !== qParam) setQ(qParam);
    if (prev.filterSig !== filterSig) setPage(1);
    setPrev({ traceParam, qParam, filterSig });
  }

  const setParam = (k: string, v: string | null) => {
    const sp = new URLSearchParams(params.toString());
    if (v) sp.set(k, v); else sp.delete(k);
    router.replace(`${path}?${sp}`, { scroll: false });
  };

  const projects = useProjects();
  const connectors = useConnectors();
  const dims = useCostBreakdown(spec, key);
  const scoped = useCostBreakdown(spec, key, { project_id: project || undefined, environment: env || undefined });
  const ov = useOverviewMetrics(spec, key);
  const range = useMemo(() => resolveTimeRange(spec), [spec]);
  const days = useMemo(() => fillDays(scoped.data?.time_series ?? [], range.from, range.to), [scoped.data, range]);
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const traces = useTraces(spec, key, {
    project_id: project || undefined, agent: agent || undefined, environment: env || undefined, model_name: model || undefined,
    success: status === "" ? undefined : status === "ok", connector_id: source || undefined, page, page_size: PAGE,
  }, { refetchInterval: live && page === 1 ? 15_000 : false });

  const pageItems = (traces.data?.items ?? []).filter((s) => {
    if (!q) return true;
    const t = q.toLowerCase();
    return s.span_name.toLowerCase().includes(t) || (s.model_name ?? "").toLowerCase().includes(t) || s.trace_id.toLowerCase().includes(t);
  });
  const items = pageItems.filter((s) => kind === "all" || s.span_kind === kind);
  const kindCount = (k: string) => pageItems.filter((s) => s.span_kind === k).length;
  const total = traces.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const sample = traces.data?.items ?? [];
  const sampleFailed = sample.filter((s) => !s.success).length;
  const filtered = Boolean(project || env || agent || model || status || source);
  const errRate = filtered || !ov.data ? (sample.length ? (sampleFailed / sample.length) * 100 : 0) : ov.data.error_rate;
  const durs = sample.map((s) => s.duration_ms ?? 0).sort((a, b) => a - b);
  const avgMs = filtered || !ov.data ? (durs.length ? durs.reduce((a, b) => a + b, 0) / durs.length : 0) : ov.data.avg_latency_ms;
  const p95 = filtered || !ov.data ? (durs.length ? durs[Math.min(durs.length - 1, Math.floor(durs.length * 0.95))] : 0) : ov.data.p95_latency_ms;
  const hist = BUCKETS.map(([hi], i) => durs.filter((d) => d < hi && d >= (i ? BUCKETS[i - 1][0] : 0)).length);
  const spend = (scoped.data?.time_series ?? []).reduce((a, d) => a + d.total_cost_usd, 0);
  const callsTotal = (scoped.data?.time_series ?? []).reduce((a, d) => a + d.total_calls, 0);
  const maxDur = Math.max(1, ...items.map((s) => s.duration_ms ?? 0));
  const newest = sample[0]?.started_at;

  return (
    <>
      <PageHead title="Traces" sub={`Every span from the SDK and cloud connectors in the ${rangePhrase(spec)}. Click a row for the full trace.`}
        actions={<>
          <button type="button" className="btn" onClick={() => setLive((l) => !l)} aria-pressed={live}>
            {live ? <><span className="live" aria-hidden />Live</> : <><Play className="ic" aria-hidden />Paused</>}
            {live && <Pause className="ic" aria-hidden style={{ marginLeft: 2 }} />}
          </button>
          <TimeRangePicker />
        </>} />

      <div className="filterbar">
        <label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Filter by name, model or trace ID</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => setParam("q", q || null)} placeholder="Name, model or trace ID" /></label>
        <ChipSelect label="Project" value={project} onChange={(v) => setParam("project", v || null)} options={[{ value: "", label: "All" }, ...(projects.data?.items ?? []).map((p) => ({ value: p.id, label: labels[p.id] ?? p.name }))]} />
        <ChipSelect label="Environment" value={env} onChange={setEnv} options={[{ value: "", label: "All" }, ...(dims.data?.by_environment ?? []).filter((e) => e.dimension !== "None").map((e) => ({ value: e.dimension, label: envName(e.dimension) }))]} />
        <ChipSelect label="Model" value={model} onChange={setModel} options={[{ value: "", label: "All" }, ...(dims.data?.by_model ?? []).filter((m) => m.dimension !== "None").map((m) => ({ value: m.dimension, label: m.dimension }))]} />
        <ChipSelect label="Status" value={status} onChange={setStatus} options={[{ value: "", label: "All" }, { value: "ok", label: "Succeeded" }, { value: "err", label: "Failed" }]} />
        <ChipSelect label="Source" value={source} onChange={setSource} options={[{ value: "", label: "All" }, { value: "sdk", label: "TrustAI SDK" }, ...(connectors.data ?? []).map((c) => ({ value: c.id, label: c.name }))]} />
        {agent && <span className="chip">Agent: {agent}<button type="button" className="icon-btn sm" style={{ width: 18, height: 18 }} onClick={() => setParam("agent", null)} aria-label="Clear agent filter"><X className="ic" style={{ width: 12, height: 12 }} /></button></span>}
      </div>

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Trace figures">
        <Kpi icon={GitBranch} label="Spans" value={traces.isLoading ? <Skel w={70} h={22} /> : compact(total)}
          vis={<MiniBars values={days.slice(-12).map((d) => d.calls)} width={72} height={30} />}
          foot={newest ? <><span className="live" aria-hidden style={{ marginRight: 6 }} />Latest {ago(newest)} · {describeTimeRange(spec)}</> : describeTimeRange(spec)} />
        <Kpi icon={ShieldCheck} label="Error rate" tone={errRate > ERR_LIMIT ? "bad" : undefined}
          value={traces.isLoading ? <Skel w={60} h={22} /> : <>{errRate.toFixed(2)}<small>%</small></>}
          vis={<ErrMeter pct={errRate} />}
          foot={filtered ? `${sampleFailed} failed in the latest ${sample.length} spans` : ov.data ? `${compact(Math.round((ov.data.error_rate / 100) * ov.data.total_calls))} failed of ${compact(ov.data.total_calls)} calls` : "—"} />
        <Kpi icon={Clock} label="Response time" value={traces.isLoading ? <Skel w={110} h={22} /> : <Duo a={[ms(avgMs), "Average"]} b={[ms(p95), "Slowest 5%"]} />}
          vis={<div className="tr-hist" title={BUCKETS.map(([, l], i) => `${l}: ${hist[i]}`).join(" · ")}><MiniBars values={hist} width={66} height={30} /></div>} />
        <Kpi icon={Wallet} label="Spend" value={scoped.isLoading ? <Skel w={90} h={22} /> : usd(spend)}
          vis={<Sparkline values={days.map((d) => d.cost)} width={88} height={30} />}
          foot={callsTotal ? `${usd(spend / callsTotal)} per call · ${compact(callsTotal)} calls` : "No spend in this period"} />
      </section>

      <Card labelledBy="t-tr">
        <div className="card-h">
          <div>
            <h2 className="card-t" id="t-tr">Spans</h2>
            <p className="card-s">{compact(total)} matching · newest first · click a row to see the whole trace</p>
          </div>
          <Seg small label="Span type" value={kind} onChange={setKind} options={[
            ["all", `All ${pageItems.length}`], ["agent", `Agents ${kindCount("agent")}`], ["llm", `LLM calls ${kindCount("llm")}`], ["tool", `Tools ${kindCount("tool")}`]] as const} />
        </div>
        <div style={{ marginTop: 12 }}>
          {traces.isError ? <ErrorState error={traces.error} onRetry={() => traces.refetch()} /> : traces.isLoading ? <SkelRows rows={10} /> : !items.length ? (
            <Empty icon={GitBranch} title="No spans match">Widen the time range or clear a filter. New spans appear here within seconds of being sent.</Empty>
          ) : (
            <div className="scroll-x">
              <table className="tr-table">
                <thead><tr><th>Span</th><th>Status</th><th>Project</th><th>Tokens</th><th className="r">Cost</th><th>Duration</th><th className="r">Started</th><th aria-label="Open" /></tr></thead>
                <tbody>
                  {items.map((s) => {
                    const slow = (s.duration_ms ?? 0) > SLOW_MS;
                    const inT = s.input_tokens ?? 0, outT = s.output_tokens ?? 0;
                    return (
                      <tr key={s.id} className={`clickable${open === s.trace_id ? " sel" : ""}${s.success ? "" : " tr-fail"}`} onClick={() => setParam("trace", s.trace_id)}>
                        <td>
                          <div className="cell-main">
                            <KindIcon kind={s.span_kind} />
                            <div style={{ minWidth: 0 }}>
                              <b title={s.span_name} className="tr-name">{spanTitle(s)}{s.model_name && s.span_kind !== "llm" && <span className="tr-model">{s.model_name}</span>}</b>
                              <small>{KIND_LABEL[s.span_kind] ?? s.span_kind} · <span className="mono">{s.trace_id.slice(0, 10)}</span></small>
                            </div>
                          </div>
                        </td>
                        <td>{s.success ? <span className="ag-health ok"><i aria-hidden />OK</span>
                          : <span className="ag-health bad" title={s.error_message ?? undefined}><i aria-hidden />{s.error_type ?? "Error"}</span>}</td>
                        <td><span className="tr-proj">{s.project_id ? labels[s.project_id] ?? "Unnamed project" : "—"}</span><div className="sub">{s.connector_name ?? providerName(s.source_provider)}{s.tags?.environment ? ` · ${envName(String(s.tags.environment))}` : ""}</div></td>
                        <td>
                          {s.total_tokens != null ? (
                            <div className="tr-tok">
                              <span><b className="num">{compact(s.total_tokens)}</b><small>{compact(inT)} in · {compact(outT)} out</small></span>
                              <span className="tr-split" aria-hidden><i style={{ flex: `${inT || 1} 1 0` }} /><i style={{ flex: `${outT} 1 0` }} /></span>
                            </div>
                          ) : <span className="muted">—</span>}
                        </td>
                        <td className="r">{s.cost_usd ? <b className="num" style={{ fontWeight: 600 }}>{usd(s.cost_usd)}</b> : <span className="muted">—</span>}</td>
                        <td>
                          <div className="ag-metric" style={{ minWidth: 120, maxWidth: 170 }}>
                            <span className="ag-v"><b className="num" style={{ color: slow ? "var(--wait)" : undefined }}>{ms(s.duration_ms)}</b></span>
                            <span className="ag-bar"><i style={{ width: `${((s.duration_ms ?? 0) / maxDur) * 100}%`, background: !s.success ? "var(--danger)" : slow ? "var(--wait)" : "var(--c5)" }} /></span>
                          </div>
                        </td>
                        <td className="r"><span className="tr-when">{ago(s.started_at)}</span><div className="sub">{clock(s.started_at)}</div></td>
                        <td className="r"><span className="ag-open">Open<ArrowUpRight className="ic" aria-hidden /></span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card-foot">
          <span className="ag-legend"><span><i className="ok" />Agent run</span><span><i className="llm" />LLM call</span><span><i className="tool" />Tool call</span><span>Bars compare durations on this page · over {SLOW_MS / 1000}s in amber</span></span>
          <div className="row" style={{ gap: 10 }}>
            <span>Page {page} of {pages}</span>
            <div className="pager">
              <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="ic" aria-hidden />Newer</button>
              <button type="button" className="btn btn-sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Older<ChevronRight className="ic" aria-hidden /></button>
            </div>
          </div>
        </div>
      </Card>

      <TraceDrawer traceId={open} onClose={() => setParam("trace", null)} />
    </>
  );
}

/** Tiny meter: error rate (percent) against the 5% limit. */
function ErrMeter({ pct }: { pct: number }) {
  const f = Math.min(1, pct / (ERR_LIMIT * 2));
  const c = pct > ERR_LIMIT ? "var(--danger)" : pct > ERR_LIMIT / 2 ? "var(--wait)" : "var(--accent)";
  return (
    <svg width={88} height={30} viewBox="0 0 88 30" aria-hidden>
      <rect x={0} y={13} width={88} height={6} rx={3} fill="var(--hover)" />
      <rect x={0} y={13} width={Math.max(3, f * 88)} height={6} rx={3} fill={c} />
      <line x1={44} x2={44} y1={8} y2={24} stroke="var(--text-3)" strokeWidth={1.5} strokeLinecap="round" />
      <text x={44} y={6} textAnchor="middle" className="ax" style={{ fontSize: 8.5 }}>5%</text>
    </svg>
  );
}
