"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, FolderKanban, Plus, Search, Wallet, Zap } from "lucide-react";
import { ProjectForm } from "@/components/ProjectForm";
import { AreaSpark, MiniBars, Ring, Segments, Sparkline } from "@/components/charts";
import { Card, Delta, Empty, ErrorState, Kpi, PageHead, Pill, Seg, Skel } from "@/components/ui";
import { useClients, useCostBreakdown, useOverviewMetrics, useProjects, type Project } from "@/lib/api";
import { compact, day, share, usd, usdShort } from "@/lib/format";
import { projectLabels } from "@/lib/projects";
import { fillDays } from "@/lib/series";
import { resolveTimeRange, timeRangeKey, type TimeRangeSpec } from "@/lib/timeRange";

const MODE_TONE = { full: "wait", masked: "accent", disabled: undefined } as const;
const MODE_LABEL = { full: "Full capture", masked: "Masked", disabled: "Capture off" } as const;
const SPEC30: TimeRangeSpec = { kind: "preset", preset: "30d" };
const KEY30 = timeRangeKey(SPEC30);
const TINTS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--s2)"];
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
          {list.map((p) => <ProjectCard key={p.id} p={p} name={labels[p.id] ?? p.name} client={clientName[p.client_id]} total={spend} tint={TINTS[Math.abs([...p.client_id].reduce((a, c) => a + c.charCodeAt(0), 0)) % TINTS.length]} />)}
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

function ProjectCard({ p, name, client, total, tint }: { p: Project; name: string; client?: string; total: number; tint: string }) {
  const cost = useCostBreakdown(SPEC30, KEY30, { project_id: p.id });
  const range = useMemo(() => resolveTimeRange(SPEC30), []);
  const days = useMemo(() => fillDays(cost.data?.time_series ?? [], range.from, range.to), [cost.data, range]);
  const spend = p.total_cost_usd ?? 0, calls = p.total_calls ?? 0;
  const b = budgetState(p);
  const initials = name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <Link href={`/projects/${p.id}`} className="pj-card" style={{ ["--tint" as string]: tint } as React.CSSProperties}>
      <div className="pj-head">
        <span className="pj-mono" aria-hidden>{initials}</span>
        <div className="pj-id"><b>{name}</b><span>{client ?? p.slug}</span></div>
        <Pill tone={MODE_TONE[p.content_capture_mode]} dot>{MODE_LABEL[p.content_capture_mode]}</Pill>
      </div>
      <p className="pj-desc">{p.description || "No description yet."}</p>
      <div className="pj-money">
        <div><b className="num">{usd(spend)}</b><span>Spend · 30 days</span></div>
        <span className="pj-share" title="Share of all project spend">{share(total ? spend / total : 0)}<small>of total</small></span>
      </div>
      <div className="pj-spark">{cost.isLoading ? <Skel h={44} /> : <AreaSpark values={days.map((d) => d.cost)} color={tint} ariaLabel={`${name} daily spend, last 30 days`} />}</div>
      <div className="pj-budget">
        {b.used == null ? <span className="muted">No monthly budget</span> : (
          <>
            <span className="pj-track" aria-hidden><i style={{ width: `${Math.min(1, b.used) * 100}%`, background: TONE_COLOR[b.tone] }} /></span>
            <span style={{ color: b.tone === "over" ? "var(--danger)" : undefined }}><b>{Math.round(b.used * 100)}%</b> of {usdShort(p.monthly_budget_usd ?? 0)} budget</span>
          </>
        )}
      </div>
      <div className="pj-foot">
        <span><b>{compact(calls)}</b> calls</span>
        <span><b>{calls ? usd(spend / calls) : "—"}</b> / call</span>
        <span>Since {day(p.created_at)}</span>
        <ArrowUpRight className="ic pj-go" aria-hidden />
      </div>
    </Link>
  );
}
