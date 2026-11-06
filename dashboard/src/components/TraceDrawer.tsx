"use client";
import { useMemo, useState } from "react";
import { Bot, CircleCheck, CircleX, MessageSquare, Sparkles, Wrench } from "lucide-react";
import { niceMax } from "@/components/charts";
import { CopyButton, Drawer, ErrorState, Pill, SkelRows, Tabs } from "@/components/ui";
import { useProjects, useTrace, type Span } from "@/lib/api";
import { compact, envName, fullDate, ms, providerName, share, usd } from "@/lib/format";
import { projectLabels } from "@/lib/projects";

type Flat = { span: Span; depth: number; last: boolean };
function flatten(root: Span | undefined): Flat[] {
  const out: Flat[] = [];
  const walk = (s: Span, depth: number, last: boolean) => {
    out.push({ span: s, depth, last });
    const kids = [...s.children].sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? ""));
    kids.forEach((c, i) => walk(c, depth + 1, i === kids.length - 1));
  };
  if (root) walk(root, 0, true);
  return out;
}
const KIND_LABEL: Record<string, string> = { agent: "Agent run", llm: "LLM call", tool: "Tool call" };
const KIND_BAR: Record<string, string> = { agent: "var(--accent)", llm: "var(--c2)", tool: "var(--text-3)" };
const clean = (s: Span) => (s.span_name.includes(":") ? s.span_name.split(":").slice(1).join(":") : s.span_name);
const CAPTURE_NOTE: Record<string, string> = {
  disabled: "Content capture is off for this project, so prompts and responses aren't stored.",
  masked: "This project stores content with personal data masked.",
  full: "This project stores full prompts and responses.",
};

function KindTile({ kind, size = 22 }: { kind: string; size?: number }) {
  const k = kind === "agent" || kind === "tool" ? kind : "llm";
  return <span className={`tr-kind ${k}`} style={{ width: size, height: size, borderRadius: size > 26 ? 10 : 7 }} aria-hidden>{k === "agent" ? <Bot className="ic" /> : k === "tool" ? <Wrench className="ic" /> : <Sparkles className="ic" />}</span>;
}
const tsOf = (s: Span) => (s.started_at ? new Date(s.started_at).getTime() : 0);
const endOf = (s: Span) => (s.ended_at ? new Date(s.ended_at).getTime() : tsOf(s) + (s.duration_ms ?? 0));

type Tab = "details" | "content" | "meta";

export function TraceDrawer({ traceId, onClose }: { traceId: string | null; onClose: () => void }) {
  const { data, isLoading, isError, error, refetch } = useTrace(traceId);
  const projects = useProjects();
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const rows = useMemo(() => flatten(data), [data]);
  const [sel, setSel] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("details");
  const [prevTrace, setPrevTrace] = useState(traceId);
  if (prevTrace !== traceId) { setPrevTrace(traceId); setSel(null); setTab("details"); }
  const firstFail = rows.find((r) => !r.span.success)?.span;
  const current = rows.find((r) => r.span.span_id === sel)?.span ?? firstFail ?? rows[0]?.span;

  const t0 = rows.length ? Math.min(...rows.map((r) => tsOf(r.span))) : 0;
  const t1 = rows.length ? Math.max(...rows.map((r) => endOf(r.span))) : 1;
  const span = Math.max(1, t1 - t0);
  const { max: axisMax, step } = niceMax(span);
  const ticks: number[] = [];
  for (let v = 0; v <= axisMax + 1e-9; v += step) ticks.push(v);
  const totalCost = rows.reduce((a, r) => a + (r.span.cost_usd ?? 0), 0);
  const tokIn = rows.filter((r) => r.span.span_kind === "llm").reduce((a, r) => a + (r.span.input_tokens ?? 0), 0);
  const tokOut = rows.filter((r) => r.span.span_kind === "llm").reduce((a, r) => a + (r.span.output_tokens ?? 0), 0);
  const failed = rows.filter((r) => !r.span.success).length;
  const count = (k: string) => rows.filter((r) => r.span.span_kind === k).length;
  const root = data;
  const env = root?.tags?.environment ? envName(String(root.tags.environment)) : null;

  return (
    <Drawer open={!!traceId} onClose={onClose} wide
      lead={root ? <KindTile kind={root.span_kind} size={38} /> : undefined}
      title={root ? <span className="row" style={{ gap: 10 }}>{clean(root)}{failed ? <Pill tone="danger" icon={CircleX}>{failed} failed</Pill> : <Pill tone="accent" icon={CircleCheck}>Succeeded</Pill>}</span> : "Trace"}
      sub={root ? <>{KIND_LABEL[root.span_kind] ?? root.span_kind}{root.project_id ? ` · ${labels[root.project_id] ?? "Project"}` : ""}{env ? ` · ${env}` : ""} · {fullDate(root.started_at)}</> : undefined}
      actions={traceId && <CopyButton text={traceId} label="Copy trace ID" />}>
      {isError ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading || !data ? <SkelRows rows={8} /> : (
        <>
          <dl className="td-tiles">
            <div><dt>Duration</dt><dd>{ms(span)}</dd><small>{rows.length} spans end to end</small></div>
            <div><dt>Spans</dt><dd>{rows.length}</dd><small>{count("agent")} agent · {count("llm")} LLM · {count("tool")} tool</small></div>
            <div><dt>Tokens</dt><dd>{compact(tokIn + tokOut)}</dd>
              <span className="tr-split" aria-hidden style={{ marginTop: 6 }}><i style={{ flex: `${tokIn || 1} 1 0` }} /><i style={{ flex: `${tokOut} 1 0` }} /></span>
              <small>{compact(tokIn)} in · {compact(tokOut)} out</small></div>
            <div><dt>Cost</dt><dd>{usd(totalCost)}</dd><small>{count("llm") ? `${usd(totalCost / count("llm"))} per LLM call` : "No LLM calls"}</small></div>
          </dl>

          <section className="td-wf" aria-label="Span timeline">
            <div className="td-head"><h3>Timeline</h3>
              <span className="td-legend"><span><i style={{ background: KIND_BAR.agent }} />Agent</span><span><i style={{ background: KIND_BAR.llm }} />LLM call</span><span><i style={{ background: KIND_BAR.tool }} />Tool</span><span><i style={{ background: "var(--danger)" }} />Failed</span></span>
            </div>
            <div className="td-axis" aria-hidden>
              <span />
              <span className="td-ticks">{ticks.map((v) => <i key={v} style={{ left: `${(v / axisMax) * 100}%` }}>{ms(v)}</i>)}</span>
              <span />
            </div>
            <div className="td-rows">
              {rows.map(({ span: s, depth, last }) => {
                const left = ((tsOf(s) - t0) / axisMax) * 100, width = Math.max(0.6, ((s.duration_ms ?? 0) / axisMax) * 100);
                const color = !s.success ? "var(--danger)" : KIND_BAR[s.span_kind] ?? "var(--c5)";
                const on = current?.span_id === s.span_id;
                return (
                  <button type="button" key={s.span_id} className={`td-row${on ? " on" : ""}${s.success ? "" : " fail"}`} onClick={() => { setSel(s.span_id); }} aria-pressed={on}>
                    <span className="td-name" style={{ paddingLeft: depth * 18 }}>
                      {depth > 0 && <span className={`td-tree${last ? " last" : ""}`} style={{ left: depth * 18 - 11 }} aria-hidden />}
                      <KindTile kind={s.span_kind} />
                      <span className="td-n"><b title={s.span_name}>{clean(s)}</b><small>{KIND_LABEL[s.span_kind] ?? s.span_kind}{s.model_name && s.span_kind === "agent" ? ` · ${s.model_name}` : ""}</small></span>
                    </span>
                    <span className="td-track">
                      {ticks.slice(1).map((v) => <em key={v} style={{ left: `${(v / axisMax) * 100}%` }} aria-hidden />)}
                      <i style={{ left: `${Math.min(99.4, left)}%`, width: `${Math.min(100 - left, width)}%`, background: color }} />
                    </span>
                    <span className="td-dur"><b>{ms(s.duration_ms)}</b><small>+{ms(tsOf(s) - t0)}</small></span>
                  </button>
                );
              })}
            </div>
          </section>

          {current && (
            <section className="td-detail" aria-label="Selected span">
              <div className="td-dh">
                <KindTile kind={current.span_kind} size={30} />
                <div className="grow" style={{ minWidth: 0 }}>
                  <b className="td-dt">{clean(current)}</b>
                  <span className="small muted">{KIND_LABEL[current.span_kind] ?? current.span_kind} · started +{ms(tsOf(current) - t0)} · {share(span ? (current.duration_ms ?? 0) / span : 0)} of the trace</span>
                </div>
                {current.success ? <Pill tone="accent" icon={CircleCheck}>Succeeded</Pill> : <Pill tone="danger" icon={CircleX}>Failed</Pill>}
              </div>
              {!current.success && (
                <div className="banner bad"><CircleX className="ic" aria-hidden /><span><b>{current.error_type ?? "Error"}</b>{current.error_message ? ` — ${current.error_message}` : ""}</span></div>
              )}
              <Tabs label="Span sections" value={tab} onChange={setTab} tabs={[{ id: "details", label: "Details" }, { id: "content", label: "Input & output" }, { id: "meta", label: "Metadata", count: Object.keys({ ...current.tags, ...current.attributes }).length }]} />

              {tab === "details" && (
                <>
                  <dl className="td-facts">
                    <div><dt>Model</dt><dd>{current.model_name ?? "—"}</dd><small>{current.provider ? providerName(current.provider) : current.span_kind === "agent" && current.model_name ? "Main model of this agent" : current.span_kind === "llm" ? "Provider not reported" : "Tools don't call a model"}</small></div>
                    <div><dt>Tokens</dt><dd>{current.total_tokens != null ? compact(current.total_tokens) : "—"}</dd>
                      {current.total_tokens != null && <span className="tr-split" aria-hidden style={{ margin: "5px 0 2px" }}><i style={{ flex: `${current.input_tokens || 1} 1 0` }} /><i style={{ flex: `${current.output_tokens ?? 0} 1 0` }} /></span>}
                      <small>{current.total_tokens != null ? `${compact(current.input_tokens ?? 0)} in · ${compact(current.output_tokens ?? 0)} out` : "No tokens on this span"}</small></div>
                    <div><dt>Cost</dt><dd>{current.cost_usd ? usd(current.cost_usd) : "—"}</dd><small>{current.cost_usd && totalCost ? `${share(current.cost_usd / totalCost)} of trace cost` : "No direct cost"}</small></div>
                    <div><dt>Duration</dt><dd>{ms(current.duration_ms)}</dd><small>{share(span ? (current.duration_ms ?? 0) / span : 0)} of {ms(span)}</small></div>
                  </dl>
                  <dl className="td-kv">
                    <div><dt>Operation</dt><dd>{current.operation ?? "—"}</dd></div>
                    <div><dt>Finish reason</dt><dd>{current.finish_reason ?? "—"}</dd></div>
                    <div><dt>Source</dt><dd>{current.connector_name ?? providerName(current.source_provider)}</dd></div>
                    <div><dt>Started</dt><dd>{fullDate(current.started_at)}</dd></div>
                    <div><dt>Span ID</dt><dd className="mono">{current.span_id}</dd></div>
                    <div><dt>Parent span</dt><dd className="mono">{current.parent_span_id ?? "Root span"}</dd></div>
                  </dl>
                </>
              )}

              {tab === "content" && (
                current.input_content || current.output_content ? (
                  <div className="td-msgs">
                    <div className="td-msg in"><span className="td-who"><MessageSquare className="ic" aria-hidden />Prompt</span><p>{current.input_content ?? "Not captured"}</p></div>
                    <div className="td-msg out"><span className="td-who"><Sparkles className="ic" aria-hidden />Response{current.model_name ? ` · ${current.model_name}` : ""}</span><p>{current.output_content ?? (current.success ? "Not captured" : "No response — the call failed.")}</p></div>
                    <span className="small muted">{CAPTURE_NOTE[current.content_capture_mode ?? ""] ?? ""}</span>
                  </div>
                ) : (
                  <div className="td-empty">
                    <MessageSquare className="ic" aria-hidden />
                    <div><b>No content on this span</b><span>{current.span_kind !== "llm" ? "Prompts and responses live on LLM calls. Pick one in the timeline to read it." : CAPTURE_NOTE[current.content_capture_mode ?? ""] ?? "Content wasn't captured."}</span></div>
                  </div>
                )
              )}

              {tab === "meta" && (
                Object.keys({ ...current.tags, ...current.attributes }).length ? (
                  <table className="td-meta">
                    <thead><tr><th>Key</th><th>Value</th><th>Type</th></tr></thead>
                    <tbody>
                      {[...Object.entries(current.tags ?? {}).map(([k, v]) => [k, v, "Tag"] as const), ...Object.entries(current.attributes ?? {}).map(([k, v]) => [k, v, "Attribute"] as const)].map(([k, v, t]) => (
                        <tr key={t + k}><td className="mono">{k}</td><td>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td><td><span className="tag">{t}</span></td></tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="small muted">No tags or attributes on this span.</p>
              )}
            </section>
          )}
        </>
      )}
    </Drawer>
  );
}
