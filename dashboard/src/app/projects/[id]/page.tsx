"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Bot, DollarSign, Pencil, ShieldCheck, Wallet, Zap } from "lucide-react";
import { ApiKeysCard } from "@/components/ApiKeys";
import { BreakdownRow, SpanFeed } from "@/components/blocks";
import { BarChart, MiniBars } from "@/components/charts";
import { ProjectForm, CAPTURE_LABEL } from "@/components/ProjectForm";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { Card, CardHeader, Empty, ErrorState, Kpi, MoreLink, PageHead, Pill, Skel, SkelRows, StatStrip } from "@/components/ui";
import { useCostBreakdown, useProject, useProjectAgents, useTraces } from "@/lib/api";
import { compact, day, ms, pct, usd, usdShort } from "@/lib/format";
import { fillDays, slices } from "@/lib/series";
import { describeTimeRange, resolveTimeRange } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const { spec, key } = useTimeRange();
  const [edit, setEdit] = useState(false);
  const project = useProject(id, 30);
  const cost = useCostBreakdown(spec, key, { project_id: id });
  const agents = useProjectAgents(id, 30);
  const traces = useTraces(spec, key, { project_id: id, page_size: 30 }, { refetchInterval: 20_000 });
  const range = useMemo(() => resolveTimeRange(spec), [spec]);
  const days = useMemo(() => fillDays(cost.data?.time_series ?? [], range.from, range.to), [cost.data, range]);
  const p = project.data;
  const total = cost.data ? cost.data.by_model.reduce((a, d) => a + d.total_cost_usd, 0) : 0;
  const calls = cost.data ? cost.data.by_model.reduce((a, d) => a + d.total_calls, 0) : 0;
  const errors = (traces.data?.items ?? []).filter((s) => !s.success).length;

  if (project.isError) return <Card><ErrorState error={project.error} onRetry={() => project.refetch()} /></Card>;

  const budgetUse = p?.monthly_budget_usd ? (p.total_cost_usd ?? 0) / p.monthly_budget_usd : null;
  return (
    <>
      <PageHead
        kicker={<><Link href="/projects">Projects</Link><span>/</span><span>{p?.slug ?? "…"}</span></>}
        title={p ? <span className="row" style={{ gap: 10 }}>{p.name}<Pill tone={p.is_active ? "accent" : undefined} dot>{p.is_active ? "Active" : "Inactive"}</Pill></span> : <Skel w={240} h={24} />}
        sub={p?.description || (p ? `Created ${day(p.created_at)} · ${CAPTURE_LABEL[p.content_capture_mode]}` : undefined)}
        actions={<>
          <TimeRangePicker />
          <button type="button" className="btn" onClick={() => setEdit(true)} disabled={!p}><Pencil className="ic" aria-hidden />Edit project</button>
        </>}
      />

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Project figures">
        <Kpi icon={DollarSign} label="Spend" value={cost.isLoading ? <Skel w={80} h={22} /> : usd(total)} vis={<MiniBars values={days.slice(-9).map((d) => d.cost)} />} foot={describeTimeRange(spec)} />
        <Kpi icon={Zap} label="AI calls" value={cost.isLoading ? <Skel w={60} h={22} /> : compact(calls)} vis={<MiniBars values={days.slice(-9).map((d) => d.calls)} />} foot={calls ? `${usd(total / calls)} per call` : "No calls in this period"} />
        <Kpi icon={Wallet} label="Monthly budget" tone={budgetUse != null && budgetUse > 1 ? "bad" : budgetUse != null && budgetUse > 0.8 ? "wait" : undefined}
          value={p?.monthly_budget_usd ? usd(p.monthly_budget_usd) : "Not set"}
          foot={budgetUse != null ? `${Math.round(budgetUse * 100)}% used in the last 30 days (${usd(p?.total_cost_usd ?? 0)})` : "Set one to get budget tracking"} />
        <Kpi icon={ShieldCheck} label="Failed spans" tone={errors ? "bad" : undefined} value={traces.isLoading ? <Skel w={40} h={22} /> : `${errors}`} foot={`In the latest ${traces.data?.items.length ?? 0} spans`} />
      </section>

      <div className="split-l">
        <Card labelledBy="t-ds">
          <CardHeader id="t-ds" title="Daily spend" sub={`USD per day · ${describeTimeRange(spec)}`} action={<MoreLink href="/cost">Cost insights</MoreLink>} />
          <div style={{ padding: "14px 18px 0" }}>
            <StatStrip items={[["Total", usd(total)], ["Average per day", usd(days.length ? total / days.length : 0)], ["Days with spend", `${days.filter((d) => d.cost > 0).length} of ${days.length}`]]} />
          </div>
          <div style={{ flex: 1, minHeight: 200, margin: 18, marginTop: 14 }}>
            {cost.isLoading ? <Skel h={200} /> : <BarChart height="fill" ariaLabel="Project spend per day" data={days.map((d) => ({ label: d.label, long: d.long, value: d.cost, extra: [{ name: "AI calls", value: compact(d.calls) }] }))} fmt={(v) => usd(v)} fmtAxis={usdShort} />}
          </div>
        </Card>
        <Card labelledBy="t-bk">
          <CardHeader id="t-bk" title="Where spend goes" sub={`Share of ${usd(total)}`} />
          {cost.isLoading ? <SkelRows rows={6} /> : (
            <div className="bk">
              <BreakdownRow title="By model" slices={slices(cost.data?.by_model, "model")} />
              <BreakdownRow title="By provider" slices={slices(cost.data?.by_provider, "provider")} />
              <BreakdownRow title="By environment" slices={slices(cost.data?.by_environment, "environment")} />
            </div>
          )}
        </Card>
      </div>

      <div className="split-wide">
        <Card labelledBy="t-ag" style={{ height: 340 }}>
          <CardHeader id="t-ag" title="Agents" sub="Registered for this project · last 30 days" action={<MoreLink href="/agents">All agents</MoreLink>} />
          <div className="scroll-y sticky-head" style={{ flex: 1, minHeight: 0, marginTop: 12 }}>
            {agents.isError ? <ErrorState error={agents.error} compact /> : agents.isLoading ? <SkelRows rows={4} /> : !agents.data?.items.length ? (
              <Empty icon={Bot} title="No registered agents">Agents appear here once they are registered for this project.</Empty>
            ) : (
              <table>
                <thead><tr><th>Agent</th><th>Type</th><th className="r">Spend</th><th className="r">Calls</th><th className="r">Avg. duration</th><th>Error rate</th></tr></thead>
                <tbody>
                  {agents.data.items.map((a) => (
                    <tr key={a.id}>
                      <td><div className="cell-main"><span className="ico neutral" aria-hidden><Bot className="ic" /></span><div><b>{a.name}</b><small>{a.slug}</small></div></div></td>
                      <td className="muted">{a.agent_type}</td>
                      <td className="r strong">{usd(a.total_cost_usd)}</td>
                      <td className="r">{compact(a.total_calls)}</td>
                      <td className="r">{ms(a.avg_duration_ms)}</td>
                      <td><span className={`sdot ${a.error_rate > 5 ? "bad" : "ok"}`}><i aria-hidden />{pct(a.error_rate, a.error_rate ? 2 : 0)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
        <Card labelledBy="t-live" style={{ height: 340 }}>
          <CardHeader id="t-live" title="Recent activity" bordered sub={traces.data ? `${compact(traces.data.total)} spans in this period` : "Recent spans"} action={<span className="pill pill-accent"><i className="live" aria-hidden />Live</span>} />
          {traces.isError ? <div className="card-b"><ErrorState error={traces.error} compact /></div> : traces.isLoading ? <SkelRows rows={5} /> : <SpanFeed spans={traces.data?.items ?? []} />}
          <div className="card-foot"><span>Most recent first</span><MoreLink href={`/traces?project=${id}`}>Open in traces</MoreLink></div>
        </Card>
      </div>

      <ApiKeysCard projectId={id} />
      {p && <ProjectForm open={edit} onClose={() => setEdit(false)} project={p} />}
    </>
  );
}
