/** Helpers that turn API breakdowns into chart-ready data. */
import type { DayPoint, Dim } from "@/lib/api";
import { SERIES, SEQ, type Slice } from "@/components/charts";
import { envName, providerName } from "@/lib/format";

const dayKey = (d: Date) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
const labelFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const longFmt = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

export interface FilledDay { key: string; label: string; long: string; cost: number; calls: number; tokens: number }

/** One entry per UTC day in [from, to], with zeros where the rollups have no row. */
export function fillDays(points: DayPoint[], from: Date, to: Date): FilledDay[] {
  const byDay = new Map(points.map((p) => [p.date.slice(0, 10), p]));
  const out: FilledDay[] = [];
  const d = new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate()));
  const end = Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), to.getUTCDate());
  let guard = 0;
  while (d.getTime() <= end && guard++ < 400) {
    const k = dayKey(d);
    const p = byDay.get(k);
    out.push({ key: k, label: labelFmt.format(d), long: longFmt.format(d), cost: p?.total_cost_usd ?? 0, calls: p?.total_calls ?? 0, tokens: p?.total_tokens ?? 0 });
    d.setUTCDate(d.getUTCDate() + 1);
  }
  // Include any rollup days that fall outside the computed window (clock skew, custom ranges).
  points.forEach((p) => {
    const k = p.date.slice(0, 10);
    if (!out.some((o) => o.key === k)) {
      const dd = new Date(`${k}T00:00:00Z`);
      out.push({ key: k, label: labelFmt.format(dd), long: longFmt.format(dd), cost: p.total_cost_usd, calls: p.total_calls, tokens: p.total_tokens });
    }
  });
  return out.sort((a, b) => a.key.localeCompare(b.key));
}

/**
 * Turn a breakdown into ring slices: up to `max` named slices (fixed colour order) plus "Other".
 * `kind` picks the label formatter and the palette (environments are ordinal → sequential).
 */
export function slices(dims: Dim[] | undefined, kind: "model" | "provider" | "environment" | "plain", max = 4, label?: (id: string) => string): Slice[] {
  const rows = (dims ?? []).filter((d) => d.total_cost_usd > 0 || d.total_calls > 0);
  const name = label ?? ((id: string) => (kind === "provider" ? providerName(id) : kind === "environment" ? envName(id) : id === "None" ? "Not set" : id));
  const palette = kind === "environment" ? SEQ : SERIES;
  const head = rows.slice(0, max).map((d, i) => ({ name: name(d.dimension), value: d.total_cost_usd, color: palette[i % palette.length] }));
  const rest = rows.slice(max).reduce((a, d) => a + d.total_cost_usd, 0);
  if (rest > 0) head.push({ name: "Other", value: rest, color: "var(--c5)" });
  return head;
}
