/** Display formatting shared by every page. */

/** Currency with sensible precision: tiny AI costs keep 4–6 decimals, larger ones keep 2. */
export function usd(value: number | null | undefined, decimals?: number): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (decimals != null) return `$${value.toFixed(decimals)}`;
  if (value === 0) return "$0.00";
  const abs = Math.abs(value);
  if (abs < 0.01) return `$${value.toFixed(6).replace(/0{1,2}$/, "")}`;
  if (abs < 1) return `$${value.toFixed(4)}`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

/** Short currency for axes and legends: $0, $0.02, $1.4K. */
export function usdShort(value: number): string {
  if (value === 0) return "$0";
  const abs = Math.abs(value);
  if (abs >= 1000) return `$${(value / 1000).toFixed(abs >= 10000 ? 0 : 1)}K`;
  if (abs >= 100) return `$${Math.round(value)}`;
  if (abs >= 1) return `$${value.toFixed(abs >= 10 ? 0 : 1)}`;
  if (abs >= 0.01) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(4)}`;
}

/** Compact count: 1.2K, 3.4M. */
export function compact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return Math.round(value).toLocaleString("en-US");
}

export function int(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Math.round(value).toLocaleString("en-US");
}

/** Latency: 640ms, 2.50s. */
export function ms(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

/** Percent from a 0–100 number. */
export function pct(value: number | null | undefined, decimals = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

/** Percent from a 0–1 share, trimming decimals once it's large. */
export function share(fraction: number): string {
  const v = fraction * 100;
  if (v === 0) return "0%";
  if (v < 0.1) return "<0.1%";
  return `${v.toFixed(v >= 10 ? 0 : 1)}%`;
}

const timeFmt = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });
const timeSecFmt = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const dayTimeFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const fullFmt = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "Today, 3:45 PM" or "Nov 4, 3:45 PM". */
export function when(iso: string | null | undefined, withSeconds = false): string {
  const d = toDate(iso);
  if (!d) return "—";
  const today = d.toDateString() === new Date().toDateString();
  if (today) return `Today, ${(withSeconds ? timeSecFmt : timeFmt).format(d)}`;
  return dayTimeFmt.format(d);
}
export function clock(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? timeFmt.format(d) : "—";
}
export function day(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? dayFmt.format(d) : "—";
}
export function fullDate(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? fullFmt.format(d) : "—";
}
/** "12s ago", "4m ago", "3h ago", "2d ago". */
export function ago(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return "—";
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

/** snake_case / dotted ids → Title Case. */
export function humanize(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/[._-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Friendly names for provider / source identifiers sent by the collectors. */
const PROVIDER_NAMES: Record<string, string> = {
  azure_openai: "Azure OpenAI",
  azure_foundry: "Azure AI Foundry",
  azure_app_insights: "Azure App Insights",
  aws_bedrock: "AWS Bedrock",
  gcp_vertex: "Google Vertex AI",
  databricks_mlflow: "Databricks MLflow",
  openai: "OpenAI",
  anthropic: "Anthropic",
  trustai_sdk: "TrustAI SDK",
};
export function providerName(id: string | null | undefined): string {
  if (!id || id === "None" || id === "null") return "Not set";
  return PROVIDER_NAMES[id] ?? humanize(id);
}

/** Environment labels: the API returns "None" when a span had no environment tag. */
export function envName(id: string | null | undefined): string {
  if (!id || id === "None" || id === "null") return "Not set";
  return id.charAt(0).toUpperCase() + id.slice(1);
}

/** Short id for display: first 8 chars. */
export function shortId(id: string | null | undefined, n = 8): string {
  if (!id) return "—";
  return id.length > n ? `${id.slice(0, n)}…` : id;
}

/** Signed trend label from a percent change. */
export function trend(pctChange: number | null | undefined): { label: string; dir: "up" | "down" | "flat" } {
  if (pctChange == null || Math.abs(pctChange) < 0.05) return { label: "0%", dir: "flat" };
  return { label: `${pctChange > 0 ? "+" : "−"}${Math.abs(pctChange).toFixed(1)}%`, dir: pctChange > 0 ? "up" : "down" };
}
