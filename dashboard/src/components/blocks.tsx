"use client";
/** Composite blocks reused across pages. */
import { useState } from "react";
import Link from "next/link";
import { GitBranch } from "lucide-react";
import { Ring, type Slice } from "@/components/charts";
import { Empty } from "@/components/ui";
import type { Span } from "@/lib/api";
import { clock, compact, usd, share, when } from "@/lib/format";

/** One breakdown row: small ring + two-column legend. Rows stack top to bottom. */
export function BreakdownRow({ title, slices }: { title: string; slices: Slice[] }) {
  const [active, setActive] = useState<number | null>(null);
  const total = slices.reduce((a, s) => a + s.value, 0);
  const top = slices[active ?? 0];
  return (
    <div className="bk-sec">
      <Ring slices={slices} size={72} stroke={8} active={active} onActive={setActive}
        ariaLabel={`${title}: ${slices.map((s) => `${s.name} ${share(total ? s.value / total : 0)}`).join(", ")}`}
        center={<b>{top && total ? share(top.value / total) : "—"}</b>} />
      <div className="bk-body">
        <h3>{title}</h3>
        {slices.length ? (
          <ul>
            {slices.map((s, i) => (
              <li key={s.name + i} className={active === i ? "on" : undefined} onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}>
                <i style={{ background: s.color }} aria-hidden />
                <span className="n" title={s.name}>{s.name}</span>
                <span className="v"><b>{share(total ? s.value / total : 0)}</b> · {usd(s.value)}</span>
              </li>
            ))}
          </ul>
        ) : <span className="small muted">No spend in this period</span>}
      </div>
    </div>
  );
}

/** Compact live list of recent spans. */
export function SpanFeed({ spans, emptyText = "No spans in this period yet." }: { spans: Span[]; emptyText?: string }) {
  if (!spans.length) return <Empty icon={GitBranch} title="No activity yet">{emptyText}</Empty>;
  return (
    <ul className="feed">
      {spans.map((s) => {
        const [base, suffix] = s.span_name.includes(":") ? [s.span_name.split(":")[0], s.span_name.split(":").slice(1).join(":")] : [s.span_name, s.model_name ?? ""];
        const kind = !s.success ? "bad" : s.span_kind === "tool" ? "tool" : s.span_kind === "agent" ? "agent" : "";
        const meta = !s.success
          ? `${s.error_type ?? "Error"}${s.error_message ? ` · ${s.error_message}` : ""}`
          : [s.model_name, s.total_tokens != null ? `${compact(s.total_tokens)} tokens` : null, s.duration_ms != null ? `${Math.round(s.duration_ms)}ms` : null].filter(Boolean).join(" · ");
        return (
          <li key={s.id}>
            <Link href={`/traces?trace=${encodeURIComponent(s.trace_id)}`} style={{ display: "contents" }}>
              <span className={`dot ${kind}`} aria-hidden />
              <span className="n"><span>{base}</span>{suffix && <em>{suffix}</em>}</span>
              <span className="t" title={when(s.started_at, true)}>{clock(s.started_at)}</span>
              <span className={`m${!s.success ? " bad" : ""}`}>{meta || s.span_kind}</span>
              <span className="c">{s.cost_usd != null && s.cost_usd > 0 ? usd(s.cost_usd) : ""}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
