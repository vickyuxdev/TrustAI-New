"use client";
import { useMemo, useState } from "react";
import { Bot, CircleCheck, CircleX, Sparkles, Wrench, Workflow } from "lucide-react";
import { CopyButton, Drawer, ErrorState, Pill, SkelRows, StatStrip } from "@/components/ui";
import { useTrace, type Span } from "@/lib/api";
import { compact, fullDate, ms, providerName, usd } from "@/lib/format";

type Flat = { span: Span; depth: number };
function flatten(root: Span | undefined): Flat[] {
  const out: Flat[] = [];
  const walk = (s: Span, depth: number) => { out.push({ span: s, depth }); [...s.children].sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? "")).forEach((c) => walk(c, depth + 1)); };
  if (root) walk(root, 0);
  return out;
}
const KIND_ICON = { llm: Sparkles, tool: Wrench, agent: Bot } as Record<string, typeof Bot>;
const KIND_COLOR = { llm: "var(--c1)", tool: "var(--c2)", agent: "var(--c4)" } as Record<string, string>;

function Json({ value }: { value: Record<string, unknown> }) {
  const text = JSON.stringify(value, null, 2);
  if (!Object.keys(value ?? {}).length) return <span className="small muted">None</span>;
  return <pre className="code">{text}</pre>;
}

export function TraceDrawer({ traceId, onClose }: { traceId: string | null; onClose: () => void }) {
  const { data, isLoading, isError, error, refetch } = useTrace(traceId);
  const rows = useMemo(() => flatten(data), [data]);
  const [sel, setSel] = useState<string | null>(null);
  const [prevTrace, setPrevTrace] = useState(traceId);
  if (prevTrace !== traceId) { setPrevTrace(traceId); setSel(null); }
  const current = rows.find((r) => r.span.span_id === sel)?.span ?? rows[0]?.span;

  const t0 = Math.min(...rows.map((r) => (r.span.started_at ? new Date(r.span.started_at).getTime() : Infinity)));
  const t1 = Math.max(...rows.map((r) => {
    const s = r.span.started_at ? new Date(r.span.started_at).getTime() : 0;
    return r.span.ended_at ? new Date(r.span.ended_at).getTime() : s + (r.span.duration_ms ?? 0);
  }));
  const spanTotal = Math.max(1, t1 - t0);
  const totalCost = rows.reduce((a, r) => a + (r.span.cost_usd ?? 0), 0);
  const totalTok = rows.reduce((a, r) => a + (r.span.total_tokens ?? 0), 0);
  const failed = rows.filter((r) => !r.span.success).length;

  return (
    <Drawer open={!!traceId} onClose={onClose}
      title={data ? data.span_name : "Trace"}
      sub={traceId ? <span className="row" style={{ gap: 8 }}><span className="id">Trace {traceId}</span></span> : undefined}
      actions={traceId && <CopyButton text={traceId} label="Copy ID" />}>
      {isError ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading || !data ? <SkelRows rows={8} /> : (
        <>
          <StatStrip items={[
            ["Spans", String(rows.length)],
            ["Duration", ms(Number.isFinite(spanTotal) ? spanTotal : data.duration_ms)],
            ["Tokens", compact(totalTok)],
            ["Cost", usd(totalCost)],
            ["Status", failed ? `${failed} failed` : "All succeeded"],
          ]} />

          <section aria-label="Span waterfall">
            <div className="card-t" style={{ marginBottom: 8 }}>Waterfall</div>
            <div className="wf">
              {rows.map(({ span, depth }) => {
                const s = span.started_at ? new Date(span.started_at).getTime() : t0;
                const dur = span.duration_ms ?? 0;
                const left = ((s - t0) / spanTotal) * 100, width = Math.max(0.8, (dur / spanTotal) * 100);
                const Icon = KIND_ICON[span.span_kind] ?? Workflow;
                const color = !span.success ? "var(--danger)" : KIND_COLOR[span.span_kind] ?? "var(--c5)";
                return (
                  <div key={span.span_id} className={`wf-row${current?.span_id === span.span_id ? " sel" : ""}`} role="button" tabIndex={0}
                    onClick={() => setSel(span.span_id)} onKeyDown={(e) => { if (e.key === "Enter") setSel(span.span_id); }}>
                    <span className="wf-name" style={{ paddingLeft: depth * 14 }}>
                      <Icon className="ic" style={{ width: 13, height: 13, color }} aria-hidden />
                      <span title={span.span_name}>{span.span_name}</span>
                    </span>
                    <span className="wf-track" aria-hidden><i style={{ left: `${Math.min(99, left)}%`, width: `${Math.min(100 - left, width)}%`, background: color }} /></span>
                    <span className="wf-dur">{ms(span.duration_ms)}</span>
                  </div>
                );
              })}
            </div>
          </section>

          {current && (
            <section className="stack" aria-label="Span details">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="card-t">{current.span_name}</div>
                {current.success ? <Pill tone="accent" icon={CircleCheck}>Succeeded</Pill> : <Pill tone="danger" icon={CircleX}>Failed</Pill>}
              </div>
              {!current.success && (
                <div className="banner bad"><CircleX className="ic" aria-hidden /><span><b>{current.error_type ?? "Error"}</b>{current.error_message ? ` · ${current.error_message}` : ""}</span></div>
              )}
              <dl className="kv">
                <dt>Kind</dt><dd>{current.span_kind}</dd>
                <dt>Model</dt><dd>{current.model_name ?? "—"}</dd>
                <dt>Provider</dt><dd>{current.provider ? providerName(current.provider) : "—"}</dd>
                <dt>Operation</dt><dd>{current.operation ?? "—"}</dd>
                <dt>Tokens</dt><dd>{current.total_tokens != null ? `${compact(current.total_tokens)} (in ${compact(current.input_tokens ?? 0)} · out ${compact(current.output_tokens ?? 0)})` : "—"}</dd>
                <dt>Cost</dt><dd>{usd(current.cost_usd)}</dd>
                <dt>Duration</dt><dd>{ms(current.duration_ms)}</dd>
                <dt>Started</dt><dd>{fullDate(current.started_at)}</dd>
                <dt>Finish reason</dt><dd>{current.finish_reason ?? "—"}</dd>
                <dt>Source</dt><dd>{current.connector_name ?? providerName(current.source_provider)}</dd>
                <dt>Span ID</dt><dd>{current.span_id}</dd>
              </dl>
              <div className="stack-sm">
                <div className="row" style={{ justifyContent: "space-between" }}><span className="card-t" style={{ fontSize: 12.5 }}>Input</span><span className="small muted">Capture: {current.content_capture_mode ?? "—"}</span></div>
                {current.input_content ? <pre className="code">{current.input_content}</pre> : <span className="small muted">No input captured for this span.</span>}
              </div>
              <div className="stack-sm">
                <span className="card-t" style={{ fontSize: 12.5 }}>Output</span>
                {current.output_content ? <pre className="code">{current.output_content}</pre> : <span className="small muted">No output captured for this span.</span>}
              </div>
              <div className="grid-2">
                <div className="stack-sm"><span className="card-t" style={{ fontSize: 12.5 }}>Tags</span><Json value={current.tags} /></div>
                <div className="stack-sm"><span className="card-t" style={{ fontSize: 12.5 }}>Attributes</span><Json value={current.attributes} /></div>
              </div>
            </section>
          )}
        </>
      )}
    </Drawer>
  );
}
