/**
 * Global time-range model shared by the top-bar picker and every data page.
 *
 * The selection lives in the URL so it survives reloads and can be shared:
 *   ?range=24h                         → a relative preset (default 7d when absent)
 *   ?from=2026-10-01T00:00:00.000Z&to=… → an absolute custom range
 *
 * Relative presets are resolved against "now" at fetch time (see resolveTimeRange), so
 * React Query keys stay stable while auto-refresh keeps sliding the window forward.
 */

export type PresetKey = "15m" | "1h" | "24h" | "7d" | "30d" | "90d";

export interface Preset {
  key: PresetKey;
  /** Menu label, e.g. "Last 24 hours". */
  label: string;
  /** Compact label for chips/buttons, e.g. "24h". */
  short: string;
  ms: number;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
export const DAY = 24 * HOUR;

export const PRESETS: readonly Preset[] = [
  { key: "15m", label: "Last 15 minutes", short: "15m", ms: 15 * MINUTE },
  { key: "1h", label: "Last hour", short: "1h", ms: HOUR },
  { key: "24h", label: "Last 24 hours", short: "24h", ms: DAY },
  { key: "7d", label: "Last 7 days", short: "7d", ms: 7 * DAY },
  { key: "30d", label: "Last 30 days", short: "30d", ms: 30 * DAY },
  { key: "90d", label: "Last 90 days", short: "90d", ms: 90 * DAY },
];

export const DEFAULT_PRESET: PresetKey = "7d";

/** Longest look-back the API accepts (overview caps period_days at 90). */
export const MAX_RANGE_MS = 90 * DAY;

/** A time-range selection as stored in the URL: a preset, or fixed ISO bounds. */
export type TimeRangeSpec =
  | { kind: "preset"; preset: PresetKey }
  | { kind: "custom"; from: string; to: string };

/** Concrete bounds for one fetch. */
export interface ResolvedRange {
  from: Date;
  to: Date;
}

/** URL parameter names owned by the time range (other params are left untouched). */
export const RANGE_PARAMS = ["range", "from", "to"] as const;

/** Minimal read interface satisfied by URLSearchParams and Next's ReadonlyURLSearchParams. */
interface ParamReader {
  get(name: string): string | null;
}

/** Returns the preset definition for a key. */
export function getPreset(key: PresetKey): Preset {
  return PRESETS.find(p => p.key === key) ?? PRESETS[3];
}

function isPresetKey(value: string | null): value is PresetKey {
  return value != null && PRESETS.some(p => p.key === value);
}

function parseIso(value: string | null): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * Reads the selection from URL params. Invalid or reversed custom bounds fall back to the
 * preset (or the default), so a hand-edited URL can never produce an empty/broken query.
 */
export function parseTimeRangeSpec(params: ParamReader): TimeRangeSpec {
  const from = parseIso(params.get("from"));
  const to = parseIso(params.get("to"));
  if (from && to && from.getTime() < to.getTime()) {
    return { kind: "custom", from: from.toISOString(), to: to.toISOString() };
  }
  const range = params.get("range");
  return { kind: "preset", preset: isPresetKey(range) ? range : DEFAULT_PRESET };
}

/** Writes the selection into a copy of `params`, preserving unrelated params. */
export function writeTimeRangeSpec(params: ParamReader & { toString(): string }, spec: TimeRangeSpec): URLSearchParams {
  const next = new URLSearchParams(params.toString());
  RANGE_PARAMS.forEach(k => next.delete(k));
  if (spec.kind === "preset") {
    next.set("range", spec.preset);
  } else {
    next.set("from", spec.from);
    next.set("to", spec.to);
  }
  return next;
}

/** Stable string for React Query keys and memo deps. */
export function timeRangeKey(spec: TimeRangeSpec): string {
  return spec.kind === "preset" ? spec.preset : `${spec.from}~${spec.to}`;
}

/** Resolves the spec into concrete bounds; presets end at `now`. */
export function resolveTimeRange(spec: TimeRangeSpec, now: number = Date.now()): ResolvedRange {
  if (spec.kind === "custom") {
    return { from: new Date(spec.from), to: new Date(spec.to) };
  }
  return { from: new Date(now - getPreset(spec.preset).ms), to: new Date(now) };
}

/**
 * Whole-day look-back for endpoints that only take `period_days` (the backend computes
 * `now - period_days`). Covers the range's start, clamped to the API's 1–90 window.
 */
export function periodDaysFor(range: ResolvedRange, now: number = Date.now(), maxDays = 90): number {
  const days = Math.ceil((now - range.from.getTime()) / DAY);
  return Math.min(Math.max(days, 1), maxDays);
}

/**
 * Query params for the analytics API: explicit `start`/`end` (exact window) plus a
 * `period_days` fallback so older API builds still return a sensible superset.
 */
export function timeRangeQuery(spec: TimeRangeSpec, now: number = Date.now()): Record<string, string> {
  const range = resolveTimeRange(spec, now);
  return {
    start: range.from.toISOString(),
    end: range.to.toISOString(),
    period_days: String(periodDaysFor(range, now)),
  };
}

/** True when the timestamp falls inside the resolved range (inclusive start, inclusive end). */
export function isWithinRange(iso: string | null | undefined, range: ResolvedRange): boolean {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  return !Number.isNaN(t) && t >= range.from.getTime() && t <= range.to.getTime();
}

/** Range length in ms (used to pick chart bucket sizes and labels). */
export function rangeDurationMs(spec: TimeRangeSpec, now: number = Date.now()): number {
  const r = resolveTimeRange(spec, now);
  return r.to.getTime() - r.from.getTime();
}

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
});
// Same formats without the year, used when the whole range falls in the current year.
const shortDateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const shortDateTimeFmt = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
});

function isMidnight(d: Date): boolean {
  return d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0;
}

/**
 * Human label for the trigger button, e.g. "Last 7 days", "Oct 1 – Oct 15" or
 * "Oct 1, 9:00 AM – Oct 1, 5:00 PM". The year is shown only when it isn't the current one.
 */
export function describeTimeRange(spec: TimeRangeSpec, now: number = Date.now()): string {
  if (spec.kind === "preset") return getPreset(spec.preset).label;
  const from = new Date(spec.from);
  const to = new Date(spec.to);
  const dayOnly = isMidnight(from) && (isMidnight(to) || (to.getHours() === 23 && to.getMinutes() === 59));
  const thisYear = new Date(now).getFullYear();
  const sameYear = from.getFullYear() === thisYear && to.getFullYear() === thisYear;
  const fmt = dayOnly ? (sameYear ? shortDateFmt : dateFmt) : (sameYear ? shortDateTimeFmt : dateTimeFmt);
  return `${fmt.format(from)} – ${fmt.format(to)}`;
}

/** Secondary line showing the exact bounds, e.g. "Oct 23, 2026, 9:14 AM → now". */
export function describeBounds(spec: TimeRangeSpec, now: number = Date.now()): string {
  const r = resolveTimeRange(spec, now);
  return spec.kind === "preset"
    ? `${dateTimeFmt.format(r.from)} → now`
    : `${dateTimeFmt.format(r.from)} → ${dateTimeFmt.format(r.to)}`;
}

/**
 * Phrase that reads after "in the …" in page copy: "last 24 hours" or
 * "selected period (Oct 1 – Oct 15)".
 */
export function rangePhrase(spec: TimeRangeSpec): string {
  return spec.kind === "preset"
    ? getPreset(spec.preset).label.toLowerCase()
    : `selected period (${describeTimeRange(spec)})`;
}

/** Converts a Date to the value format of <input type="datetime-local"> in local time. */
export function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Validates a custom range typed into the picker. Returns an error message for the user,
 * or the spec to apply.
 */
export function validateCustomRange(
  fromLocal: string,
  toLocal: string,
  now: number = Date.now(),
): { ok: true; spec: TimeRangeSpec } | { ok: false; error: string } {
  const from = parseIso(fromLocal);
  const to = parseIso(toLocal);
  if (!from || !to) return { ok: false, error: "Enter both a start and an end." };
  if (from.getTime() >= to.getTime()) return { ok: false, error: "Start must be before end." };
  if (from.getTime() > now) return { ok: false, error: "Start can't be in the future." };
  if (now - from.getTime() > MAX_RANGE_MS + DAY) {
    return { ok: false, error: "Data is kept for 90 days. Choose a start within the last 90 days." };
  }
  return { ok: true, spec: { kind: "custom", from: from.toISOString(), to: to.toISOString() } };
}
