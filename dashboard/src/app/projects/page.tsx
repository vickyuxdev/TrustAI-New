"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { FolderKanban, Plus, Search } from "lucide-react";
import { ProjectForm } from "@/components/ProjectForm";
import { MiniBars, SERIES, Segments, Trend } from "@/components/charts";
import { Card, CardHeader, Delta, Empty, ErrorState, PageHead, Pill, ShareCell, Skel, SkelRows } from "@/components/ui";
import { useCostBreakdown, useOverviewMetrics, useProjects, type Project } from "@/lib/api";
import { compact, day, share, usd } from "@/lib/format";
import { projectLabels } from "@/lib/projects";
import { fillDays } from "@/lib/series";
import { resolveTimeRange, timeRangeKey, type TimeRangeSpec } from "@/lib/timeRange";

const MODE_TONE = { full: "wait", masked: "accent", disabled: undefined } as const;
const MODE_LABEL = { full: "Full capture", masked: "Masked", disabled: "Capture off" } as const;

export default function ProjectsPage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError, error, refetch } = useProjects(30);
  const items = useMemo(() => data?.items ?? [], [data]);
  const labels = useMemo(() => projectLabels(items), [items]);
  const list = items.filter((p) => `${p.name} ${p.slug} ${p.description ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0));
  const spend = items.reduce((a, p) => a + (p.total_cost_usd ?? 0), 0);

  return (
    <>
      <PageHead title="Projects" sub="Every AI application sending telemetry to TrustAI. Spend and calls cover the last 30 days."
        actions={<button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />New project</button>} />

      <Pulse items={items} loading={isLoading} labels={labels} />

      <Card labelledBy="t-list">
        <CardHeader id="t-list" title="All projects" sub={`${items.length} active · sorted by 30-day spend`}
          action={<label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Search projects</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search projects" /></label>} />
        <div style={{ marginTop: 12 }}>
          {isError ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading ? <SkelRows rows={6} /> : !list.length ? (
            <Empty icon={FolderKanban} title={q ? "No projects match" : "No projects yet"}
              action={!q && <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />Create your first project</button>}>
              {q ? "Try a different name or slug." : "Create a project, generate an API key and add two lines of the TrustAI SDK to start seeing data."}
            </Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead><tr><th>Project</th><th>Content capture</th><th className="r">Spend · 30d</th><th>Share of spend</th><th>Budget use</th><th className="r">AI calls</th><th className="r">Created</th></tr></thead>
                <tbody>
                  {list.map((p) => {
                    const cost = p.total_cost_usd ?? 0;
                    const used = p.monthly_budget_usd ? cost / p.monthly_budget_usd : null;
                    return (
                      <tr key={p.id} className="clickable" onClick={() => router.push(`/projects/${p.id}`)}>
                        <td><div className="cell-main"><span className="ico" aria-hidden><FolderKanban className="ic" /></span><div><b>{labels[p.id]}</b><small>{p.description || p.slug}</small></div></div></td>
                        <td><Pill tone={MODE_TONE[p.content_capture_mode]} dot>{MODE_LABEL[p.content_capture_mode]}</Pill></td>
                        <td className="r strong">{usd(cost)}</td>
                        <td><ShareCell fraction={spend ? cost / spend : 0} label={share(spend ? cost / spend : 0)} /></td>
                        <td>{used == null ? <span className="muted">No budget</span> : (
                          <span className="share" title={`${usd(cost)} of ${usd(p.monthly_budget_usd)}`}>
                            <span className="tr" aria-hidden><i style={{ width: `${Math.min(1, used) * 100}%`, background: used > 1 ? "var(--danger)" : used > 0.8 ? "var(--wait)" : "var(--accent)" }} /></span>
                            {Math.round(used * 100)}% of {usd(p.monthly_budget_usd)}
                          </span>)}
                        </td>
                        <td className="r">{compact(p.total_calls ?? 0)}</td>
                        <td className="r muted">{day(p.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      <ProjectForm open={open} onClose={() => setOpen(false)} onSaved={(p) => router.push(`/projects/${p.id}`)} />
    </>
  );
}

const SPEC30: TimeRangeSpec = { kind: "preset", preset: "30d" };
const KEY30 = timeRangeKey(SPEC30);

/** Money with the cents set smaller and muted. */
function Money({ v }: { v: number }) {
  const [whole, cents] = usd(v).split(".");
  return <>{whole}{cents != null && <span className="cents">.{cents}</span>}</>;
}

/** Portfolio summary: 30-day spend trend on the left, three compact readouts on the right. */
function Pulse({ items, loading, labels }: { items: Project[]; loading: boolean; labels: Record<string, string> }) {
  const ov = useOverviewMetrics(SPEC30, KEY30);
  const cost = useCostBreakdown(SPEC30, KEY30);
  const range = useMemo(() => resolveTimeRange(SPEC30), []);
  const days = useMemo(() => fillDays(cost.data?.time_series ?? [], range.from, range.to), [cost.data, range]);
  const spend = items.reduce((a, p) => a + (p.total_cost_usd ?? 0), 0);
  const calls = items.reduce((a, p) => a + (p.total_calls ?? 0), 0);
  const live = items.filter((p) => (p.total_calls ?? 0) > 0).length;
  const avg = days.length ? spend / days.length : 0;

  const budget = { over: 0, near: 0, ok: 0, none: 0 };
  items.forEach((p) => {
    if (!p.monthly_budget_usd) return void budget.none++;
    const u = (p.total_cost_usd ?? 0) / p.monthly_budget_usd;
    if (u > 1) budget.over++; else if (u >= 0.8) budget.near++; else budget.ok++;
  });
  const ranked = [...items].sort((a, b) => (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0));
  const top = ranked.slice(0, 3);
  const topShare = spend ? top.reduce((a, p) => a + (p.total_cost_usd ?? 0), 0) / spend : 0;

  return (
    <section className="card pulse" aria-label="Project portfolio summary">
      <div className="pulse-main">
        <div className="pm-head">
          <span className="eyebrow">Spend · last 30 days</span>
          <span className="live-chip"><i aria-hidden />{loading ? "—" : `${live} of ${items.length} projects sending data`}</span>
        </div>
        <div className="pm-value">
          <b>{loading ? <Skel w={180} h={30} /> : <Money v={spend} />}</b>
          {ov.data && <><Delta pct={ov.data.cost_trend_pct} /><span className="vs">vs previous 30 days</span></>}
        </div>
        <div className="pm-sub"><span><b>{usd(avg)}</b> per day on average</span><span className="dot-sep" aria-hidden />
          <span>{ranked[0] ? <><b>{labels[ranked[0].id] ?? ranked[0].name}</b> spends the most</> : "No spend yet"}</span></div>
        <div className="pm-chart">
          {cost.isLoading ? <Skel h={104} /> : (
            <Trend height={104} ariaLabel="Spend per day over the last 30 days" values={days.map((d) => d.cost)} labels={days.map((d) => d.label)} longs={days.map((d) => d.long)} fmt={(v) => usd(v)} />
          )}
        </div>
      </div>

      <div className="pulse-side">
        <div className="ps-row">
          <div className="ps-text">
            <span className="eyebrow">AI calls</span>
            <span className="ps-value">{loading ? "—" : compact(calls)}{ov.data && <Delta pct={ov.data.calls_trend_pct} />}</span>
            <span className="ps-sub">{calls ? `${usd(spend / calls)} per call on average` : "No calls yet"}</span>
          </div>
          <MiniBars values={days.slice(-14).map((d) => d.calls)} width={92} height={36} />
        </div>

        <div className="ps-row stack">
          <div className="ps-line">
            <span className="eyebrow">Budget health</span>
            <span className={`ps-flag${budget.over ? " bad" : ""}`}>{budget.over ? `${budget.over} over budget` : "All within budget"}</span>
          </div>
          <Segments ariaLabel="Projects by budget use" parts={[
            { value: budget.over, color: "var(--danger)", label: "Over budget" },
            { value: budget.near, color: "var(--wait)", label: "Above 80%" },
            { value: budget.ok, color: "var(--accent)", label: "On track" },
            { value: budget.none, color: "var(--line-2)", label: "No budget" },
          ]} />
          <ul className="seg-legend">
            <li><i style={{ background: "var(--danger)" }} />Over <b>{budget.over}</b></li>
            <li><i style={{ background: "var(--wait)" }} />Above 80% <b>{budget.near}</b></li>
            <li><i style={{ background: "var(--accent)" }} />On track <b>{budget.ok}</b></li>
            <li><i style={{ background: "var(--line-2)" }} />No budget <b>{budget.none}</b></li>
          </ul>
        </div>

        <div className="ps-row stack">
          <div className="ps-line">
            <span className="eyebrow">Spend concentration</span>
            <span className="ps-flag">Top 3 · <b>{share(topShare)}</b></span>
          </div>
          <Segments ariaLabel="Share of spend by project" parts={[
            ...top.map((p, i) => ({ value: p.total_cost_usd ?? 0, color: SERIES[i], label: labels[p.id] ?? p.name })),
            { value: Math.max(0, spend - top.reduce((a, p) => a + (p.total_cost_usd ?? 0), 0)), color: "var(--line-2)", label: "Other projects" },
          ]} />
          <ul className="seg-legend">
            {top.map((p, i) => <li key={p.id}><i style={{ background: SERIES[i] }} /><span className="ellipsis">{labels[p.id] ?? p.name}</span> <b>{share(spend ? (p.total_cost_usd ?? 0) / spend : 0)}</b></li>)}
          </ul>
        </div>
      </div>
    </section>
  );
}
