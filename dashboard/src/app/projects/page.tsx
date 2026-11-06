"use client";
import { createElement, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, BookOpen, FileText, FolderKanban, Headset, Plus, Receipt, ScanSearch, Search, ShieldCheck, Stethoscope, TrendingUp, Users, Wallet, Zap, type LucideIcon } from "lucide-react";
import { ProjectForm } from "@/components/ProjectForm";
import { MiniBars, Ring, Segments, Sparkline } from "@/components/charts";
import { Card, Delta, Empty, ErrorState, Kpi, PageHead, Seg, Skel } from "@/components/ui";
import { useClients, useCostBreakdown, useOverviewMetrics, useProjects, type Project } from "@/lib/api";
import { compact, day, usd, usdShort } from "@/lib/format";
import { projectLabels } from "@/lib/projects";
import { fillDays } from "@/lib/series";
import { resolveTimeRange, timeRangeKey, type TimeRangeSpec } from "@/lib/timeRange";

const SPEC30: TimeRangeSpec = { kind: "preset", preset: "30d" };
const KEY30 = timeRangeKey(SPEC30);
type Sort = "spend" | "name" | "newest";

function budgetState(p: Project) {
  if (!p.monthly_budget_usd) return { used: null as number | null, tone: "none" as const };
  const used = (p.total_cost_usd ?? 0) / p.monthly_budget_usd;
  return { used, tone: used > 1 ? ("over" as const) : used >= 0.8 ? ("near" as const) : ("ok" as const) };
}
const TONE_COLOR = { over: "var(--danger)", near: "var(--wait)", ok: "var(--accent)", none: "var(--line-2)" };

export default function ProjectsPage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("spend");
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError, error, refetch } = useProjects(30);
  const clients = useClients(30);
  const ov = useOverviewMetrics(SPEC30, KEY30);
  const cost = useCostBreakdown(SPEC30, KEY30);
  const range = useMemo(() => resolveTimeRange(SPEC30), []);
  const days = useMemo(() => fillDays(cost.data?.time_series ?? [], range.from, range.to), [cost.data, range]);
  const items = useMemo(() => data?.items ?? [], [data]);
  const prevSpec = useMemo<TimeRangeSpec>(() => ({ kind: "custom", from: new Date(range.from.getTime() - 30 * 86_400_000).toISOString(), to: range.from.toISOString() }), [range]);
  const labels = useMemo(() => projectLabels(items), [items]);
  const clientName = useMemo(() => Object.fromEntries((clients.data?.items ?? []).map((c) => [c.id, c.name])), [clients.data]);

  const spend = items.reduce((a, p) => a + (p.total_cost_usd ?? 0), 0);
  const calls = items.reduce((a, p) => a + (p.total_calls ?? 0), 0);
  const live = items.filter((p) => (p.total_calls ?? 0) > 0).length;
  const counts = { over: 0, near: 0, ok: 0, none: 0 };
  items.forEach((p) => counts[budgetState(p).tone]++);

  const list = items
    .filter((p) => `${p.name} ${p.slug} ${p.description ?? ""} ${clientName[p.client_id] ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => sort === "name" ? a.name.localeCompare(b.name) : sort === "newest" ? b.created_at.localeCompare(a.created_at) : (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0));

  return (
    <>
      <PageHead title="Projects" sub="Every AI application sending telemetry to TrustAI. Figures cover the last 30 days."
        actions={<button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />New project</button>} />

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Project figures">
        <Kpi icon={FolderKanban} label="Active projects" value={isLoading ? <Skel w={40} h={22} /> : compact(items.length)}
          vis={items.length ? <Ring size={34} stroke={5} ariaLabel={`${live} of ${items.length} sending data`} slices={[{ name: "Sending data", value: live, color: "var(--accent)" }, { name: "Idle", value: items.length - live, color: "var(--line-2)" }]} /> : undefined}
          foot={`${live} of ${items.length} sent calls in the last 30 days`} />
        <Kpi icon={Wallet} label="Spend · 30 days" value={isLoading ? <Skel w={110} h={22} /> : usd(spend)}
          vis={<Sparkline values={days.map((d) => d.cost)} width={88} height={30} />}
          foot={ov.data ? <><Delta pct={ov.data.cost_trend_pct} />vs previous 30 days</> : "Across all projects"} />
        <Kpi icon={Zap} label="AI calls · 30 days" value={isLoading ? <Skel w={80} h={22} /> : compact(calls)}
          vis={<MiniBars values={days.slice(-12).map((d) => d.calls)} width={72} height={30} />}
          foot={calls ? <>{ov.data && <Delta pct={ov.data.calls_trend_pct} />}{usd(spend / calls)} per call</> : "No calls yet"} />
        <Kpi icon={Wallet} label="Budget health" tone={counts.over ? "bad" : undefined}
          value={isLoading ? <Skel w={90} h={22} /> : counts.over ? <span style={{ color: "var(--danger)" }}>{counts.over} over</span> : "On track"}
          vis={<div style={{ width: 88 }}><Segments height={8} ariaLabel="Projects by budget use" parts={[
            { value: counts.over, color: TONE_COLOR.over, label: "Over budget" }, { value: counts.near, color: TONE_COLOR.near, label: "Above 80%" },
            { value: counts.ok, color: TONE_COLOR.ok, label: "On track" }, { value: counts.none, color: TONE_COLOR.none, label: "No budget" }]} /></div>}
          foot={`${counts.near} above 80% · ${counts.ok} on track · ${counts.none} no budget`} />
      </section>

      <div className="pj-bar">
        <div><h2 className="card-t">All projects</h2><span className="small muted">{list.length} of {items.length}</span></div>
        <div className="filterbar">
          <label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Search projects</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search projects or clients" /></label>
          <Seg small label="Sort by" value={sort} onChange={setSort} options={[["spend", "Top spend"], ["name", "Name"], ["newest", "Newest"]] as const} />
        </div>
      </div>

      {isError ? <Card><ErrorState error={error} onRetry={() => refetch()} /></Card> : isLoading ? (
        <div className="pj-grid">{Array.from({ length: 6 }, (_, i) => <div key={i} className="pj-card"><Skel h={150} /></div>)}</div>
      ) : !list.length ? (
        <Card><Empty icon={FolderKanban} title={q ? "No projects match" : "No projects yet"}
          action={!q && <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />Create your first project</button>}>
          {q ? "Try a different name, slug or client." : "Create a project, generate an API key and add two lines of the TrustAI SDK to start seeing data."}
        </Empty></Card>
      ) : (
        <div className="pj-grid">
          {list.map((p) => <ProjectCard key={p.id} p={p} name={labels[p.id] ?? p.name} prevSpec={prevSpec} />)}
          <button type="button" className="pj-card pj-new" onClick={() => setOpen(true)}>
            <span className="pj-new-i" aria-hidden><Plus className="ic" /></span>
            <b>New project</b>
            <span className="small muted">Group an AI application&apos;s agents, keys and spend</span>
          </button>
        </div>
      )}

      <ProjectForm open={open} onClose={() => setOpen(false)} onSaved={(p) => router.push(`/projects/${p.id}`)} />
    </>
  );
}

const ICONS: [RegExp, LucideIcon][] = [
  [/clinic|health|patient|medic|note/i, Stethoscope], [/support|ticket|help|service/i, Headset], [/invoice|billing|payment|finance/i, Receipt],
  [/policy|q&a|faq|knowledge|docs?/i, BookOpen], [/sales|pipeline|forecast|insight/i, TrendingUp], [/hr|people|employee/i, Users],
  [/claim|insur/i, ShieldCheck], [/search|discover/i, ScanSearch], [/contract|legal/i, FileText],
];
const iconFor = (name: string, desc = "") => createElement(ICONS.find(([r]) => r.test(name))?.[1] ?? ICONS.find(([r]) => r.test(desc))?.[1] ?? FolderKanban, { className: "ic" });

/** Low-visibility abstract shapes for the card background, tinted per client. */
function CardArt() {
  return (
    <svg className="pj-art" viewBox="0 0 240 200" aria-hidden preserveAspectRatio="xMaxYMin slice">
      {[38, 62, 86, 110, 134].map((r, i) => <circle key={r} cx="212" cy="20" r={r} fill="none" stroke="currentColor" strokeOpacity={0.09 - i * 0.012} strokeWidth="1" />)}
    </svg>
  );
}

function ProjectCard({ p, name, prevSpec }: { p: Project; name: string; prevSpec: TimeRangeSpec }) {
  const cost = useCostBreakdown(SPEC30, KEY30, { project_id: p.id });
  const prev = useCostBreakdown(prevSpec, timeRangeKey(prevSpec), { project_id: p.id });
  const spend = p.total_cost_usd ?? 0, calls = p.total_calls ?? 0;
  const prevSpend = prev.data ? prev.data.time_series.reduce((a, d) => a + d.total_cost_usd, 0) : null;
  const change = prevSpend ? ((spend - prevSpend) / prevSpend) * 100 : null;
  const model = cost.data?.by_model.find((m) => m.total_cost_usd > 0)?.dimension;
  const b = budgetState(p);
  const live = calls > 0;
  return (
    <Link href={`/projects/${p.id}`} className="pj-card">
      <CardArt />
      <div className="pj-head">
        <span className="pj-icon" aria-hidden>{iconFor(name, p.description ?? "")}</span>
        <div className="pj-id"><b title={name}>{name}</b><span>{model ?? "No model calls yet"}</span></div>
        <span className={`pj-status${live ? "" : " idle"}`}><i aria-hidden />{live ? "Monitored" : "Idle"}</span>
      </div>

      <div className="pj-total">
        <span className="pj-lbl">Total spend · 30 days</span>
        <b className="num">{usd(spend)}</b>
        <span className="pj-chg">
          {change == null ? <span className="muted">No previous period to compare</span> : (
            <><span className={change <= 0 ? "down" : "up"}>{change <= 0 ? <ArrowDown className="ic" aria-hidden /> : <ArrowUp className="ic" aria-hidden />}{Math.abs(change).toFixed(0)}%</span> vs previous 30 days</>
          )}
        </span>
      </div>

      <dl className="pj-stats">
        <div><dt>Total calls</dt><dd>{compact(calls)}</dd></div>
        <div><dt>Avg. cost / call</dt><dd>{calls ? usd(spend / calls) : "—"}</dd></div>
        <div><dt>Active since</dt><dd>{day(p.created_at)}</dd></div>
      </dl>

      <div className={`pj-budget ${b.tone}`}>
        {b.used == null ? <span className="pj-nobudget">No monthly budget set</span> : (
          <>
            <span className="pj-track" aria-hidden><i style={{ width: `${Math.min(1, b.used) * 100}%` }} /></span>
            <span className="pj-bv"><b>{Math.round(b.used * 100)}%</b><small>of {usdShort(p.monthly_budget_usd ?? 0)} budget</small></span>
          </>
        )}
      </div>
    </Link>
  );
}
