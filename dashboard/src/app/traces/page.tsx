"use client";
import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight, GitBranch, Pause, Play, Search, X } from "lucide-react";
import { TraceDrawer } from "@/components/TraceDrawer";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { Card, ChipSelect, Empty, ErrorState, PageHead, SkelRows, StatStrip } from "@/components/ui";
import { useConnectors, useCostBreakdown, useProjects, useTraces } from "@/lib/api";
import { compact, envName, ms, providerName, usd, when } from "@/lib/format";
import { projectLabels } from "@/lib/projects";
import { rangePhrase } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

const PAGE = 50;

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
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const traces = useTraces(spec, key, {
    project_id: project || undefined, agent: agent || undefined, environment: env || undefined, model_name: model || undefined,
    success: status === "" ? undefined : status === "ok", connector_id: source || undefined, page, page_size: PAGE,
  }, { refetchInterval: live && page === 1 ? 15_000 : false });

  const items = (traces.data?.items ?? []).filter((s) => {
    if (!q) return true;
    const t = q.toLowerCase();
    return s.span_name.toLowerCase().includes(t) || (s.model_name ?? "").toLowerCase().includes(t) || s.trace_id.toLowerCase().includes(t);
  });
  const total = traces.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const failed = items.filter((s) => !s.success).length;
  const cost = items.reduce((a, s) => a + (s.cost_usd ?? 0), 0);
  const avg = items.length ? items.reduce((a, s) => a + (s.duration_ms ?? 0), 0) / items.length : 0;

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

      <Card labelledBy="t-tr">
        <div className="card-h bordered" style={{ alignItems: "center" }}>
          <h2 className="card-t sr" id="t-tr">Spans</h2>
          <StatStrip items={[["Matching spans", compact(total)], ["On this page", String(items.length)], ["Failed", String(failed)], ["Avg. duration", ms(avg)], ["Cost on page", usd(cost)]]} />
        </div>
        {traces.isError ? <ErrorState error={traces.error} onRetry={() => traces.refetch()} /> : traces.isLoading ? <SkelRows rows={10} /> : !items.length ? (
          <Empty icon={GitBranch} title="No spans match">Widen the time range or clear a filter. New spans appear here within seconds of being sent.</Empty>
        ) : (
          <div className="scroll-x">
            <table>
              <thead><tr><th>Status</th><th>Span</th><th>Project</th><th>Model</th><th>Source</th><th className="r">Tokens</th><th className="r">Cost</th><th className="r">Duration</th><th className="r">Started</th></tr></thead>
              <tbody>
                {items.map((s) => (
                  <tr key={s.id} className={`clickable${open === s.trace_id ? " sel" : ""}`} onClick={() => setParam("trace", s.trace_id)}>
                    <td><span className={`sdot ${s.success ? "ok" : "bad"}`}><i aria-hidden />{s.success ? "OK" : s.error_type ?? "Error"}</span></td>
                    <td><div className="cell-main"><div><b title={s.span_name}>{s.span_name}</b><small>{s.span_kind} · {s.trace_id.slice(0, 12)}…</small></div></div></td>
                    <td className="muted">{s.project_id ? labels[s.project_id] ?? "Unnamed project" : "—"}</td>
                    <td>{s.model_name ? <span className="chip">{s.model_name}</span> : <span className="muted">—</span>}</td>
                    <td className="muted">{s.connector_name ?? providerName(s.source_provider)}</td>
                    <td className="r">{s.total_tokens != null ? compact(s.total_tokens) : "—"}</td>
                    <td className="r">{s.cost_usd ? usd(s.cost_usd) : "—"}</td>
                    <td className="r">{ms(s.duration_ms)}</td>
                    <td className="r muted nowrap">{when(s.started_at, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot">
          <span>Page {page} of {pages} · {compact(total)} spans</span>
          <div className="pager">
            <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="ic" aria-hidden />Newer</button>
            <button type="button" className="btn btn-sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Older<ChevronRight className="ic" aria-hidden /></button>
          </div>
        </div>
      </Card>

      <TraceDrawer traceId={open} onClose={() => setParam("trace", null)} />
    </>
  );
}
