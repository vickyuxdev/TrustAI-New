"use client";
import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Clock, DollarSign, FolderKanban, Layers, RefreshCw, ShieldCheck, Zap } from "lucide-react";
import { BarChart, CheckRing, MiniBars, SplitBar } from "@/components/charts";
import { BreakdownRow, SpanFeed } from "@/components/blocks";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { Card, CardHeader, Delta, Duo, Empty, ErrorState, Kpi, MoreLink, PageHead, ShareCell, Skel, SkelRows, StatStrip, Tag } from "@/components/ui";
import { useCostBreakdown, useOverviewMetrics, useProjects, useTraces } from "@/lib/api";
import { compact, ms, pct, share, shortId, usd, usdShort } from "@/lib/format";
import { projectLabels } from "@/lib/projects";
import { fillDays, slices } from "@/lib/series";
import { describeTimeRange, rangePhrase, resolveTimeRange } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

export default function OverviewPage() {
  const { spec, key } = useTimeRange();
  const qc = useQueryClient();
  const router = useRouter();
  const ov = useOverviewMetrics(spec, key);
  const cost = useCostBreakdown(spec, key);
  const projects = useProjects();
  const traces = useTraces(spec, key, { page_size: 25 }, { refetchInterval: 15_000 });

  const range = useMemo(() => resolveTimeRange(spec), [spec]);
  const days = useMemo(() => fillDays(cost.data?.time_series ?? [], range.from, range.to), [cost.data, range]);
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const m = ov.data;
  const total = cost.data ? cost.data.by_model.reduce((a, d) => a + d.total_cost_usd, 0) : m?.total_cost_usd ?? 0;
  const peak = days.reduce<typeof days[number] | null>((p, d) => (d.cost > (p?.cost ?? 0) ? d : p), null);
  const activeDays = days.filter((d) => d.cost > 0).length;
  const loading = ov.isLoading;
  const refresh = () => qc.invalidateQueries();

  return (
    <>
      <PageHead
        title="Overview Dashboard"
        sub={`Company-wide AI usage, cost and reliability for the ${rangePhrase(spec)}`}
        actions={<>
          <TimeRangePicker />
          <button type="button" className={`btn${ov.isFetching ? " spin" : ""}`} onClick={refresh}><RefreshCw className="ic" aria-hidden />Refresh</button>
        </>}
      />

      {ov.isError ? <Card><ErrorState error={ov.error} onRetry={() => ov.refetch()} /></Card> : (
        <section className="kpis" aria-label="Key figures">
          <Kpi icon={DollarSign} label="Total spend" value={loading ? <Skel w={90} h={22} /> : usd(m?.total_cost_usd)}
            vis={<MiniBars values={days.slice(-9).map((d) => d.cost)} />}
            foot={m && (m.cost_trend_pct ? <><Delta pct={m.cost_trend_pct} />vs previous period</> : <><Tag>New</Tag>Nothing in the previous period</>)} />
          <Kpi icon={Zap} label="AI calls" value={loading ? <Skel w={60} h={22} /> : compact(m?.total_calls)}
            vis={<MiniBars values={days.slice(-9).map((d) => d.calls)} />}
            foot={m && (m.calls_trend_pct ? <><Delta pct={m.calls_trend_pct} />vs previous period</> : <><Tag>New</Tag>Nothing in the previous period</>)} />
          <Kpi icon={Layers} label="Tokens used" value={loading ? <Skel w={70} h={22} /> : compact(m?.total_tokens)}
            vis={m && (m.total_input_tokens || m.total_output_tokens) ? <SplitBar parts={[{ value: m.total_input_tokens, color: "var(--accent)" }, { value: m.total_output_tokens, color: "var(--accent-line)" }]} /> : undefined}
            foot={m && (m.total_input_tokens || m.total_output_tokens ? `In ${compact(m.total_input_tokens)} · Out ${compact(m.total_output_tokens)}` : "Input / output split not reported")} />
          <Kpi icon={ShieldCheck} label="Error rate" tone={m && m.error_rate > 5 ? "bad" : undefined}
            value={loading ? <Skel w={60} h={22} /> : <>{(m?.error_rate ?? 0).toFixed(1)}<small>%</small></>}
            vis={m && <CheckRing ok={m.error_rate <= 5} />}
            foot={m && <><Tag tone={m.error_rate > 5 ? "bad" : "ok"}>{m.error_rate > 5 ? "Elevated" : "Healthy"}</Tag>{compact(Math.round((m.error_rate / 100) * m.total_calls))} failed of {compact(m.total_calls)} calls</>} />
          <Kpi icon={Clock} label="Response time" value={loading ? <Skel w={110} h={22} /> : <Duo a={[ms(m?.avg_latency_ms), "Average"]} b={[ms(m?.p95_latency_ms), "Slowest 5% (p95)"]} />} />
          <Kpi icon={FolderKanban} label="Active now" link={{ href: "/projects", label: "View details" }}
            value={loading ? <Skel w={110} h={22} /> : <Duo a={[compact(m?.active_projects), "Projects"]} b={[compact(m?.active_agents), "Agents"]} />} />
        </section>
      )}

      <div className="split-l">
        <Card labelledBy="t-ds">
          <CardHeader id="t-ds" title="Daily spend" sub={`USD per day · ${describeTimeRange(spec)}`} action={<MoreLink href="/cost">Cost insights</MoreLink>} />
          {cost.isError ? <div className="card-b"><ErrorState error={cost.error} onRetry={() => cost.refetch()} compact /></div> : (
            <>
              <div style={{ padding: "14px 18px 0" }}>
                <StatStrip items={[
                  ["Total", usd(total)],
                  ["Average per day", usd(days.length ? total / days.length : 0)],
                  ["Peak day", peak ? `${peak.label} · ${usd(peak.cost)}` : "—"],
                  ["Days with spend", `${activeDays} of ${days.length}`],
                ]} />
              </div>
              <div style={{ flex: 1, minHeight: 200, margin: "14px 18px 14px" }}>
                {cost.isLoading ? <Skel h={200} /> : (
                  <BarChart height="fill" ariaLabel="Spend per day"
                    data={days.map((d) => ({ label: d.label, long: d.long, value: d.cost, extra: [{ name: "AI calls", value: compact(d.calls) }, { name: "Tokens", value: compact(d.tokens) }] }))}
                    fmt={(v) => usd(v)} fmtAxis={usdShort} emphasis="last" />
                )}
              </div>
            </>
          )}
        </Card>

        <Card labelledBy="t-bk">
          <CardHeader id="t-bk" title="Where spend goes" sub={`Share of ${usd(total)} this period`} action={<MoreLink href="/cost">Breakdown</MoreLink>} />
          {cost.isError ? <div className="card-b"><ErrorState error={cost.error} compact /></div>
            : cost.isLoading ? <SkelRows rows={6} />
            : (
              <div className="bk">
                <BreakdownRow title="By model" slices={slices(cost.data?.by_model, "model")} />
                <BreakdownRow title="By provider" slices={slices(cost.data?.by_provider, "provider")} />
                <BreakdownRow title="By environment" slices={slices(cost.data?.by_environment, "environment")} />
              </div>
            )}
        </Card>
      </div>

      <div className="split-wide">
        <Card labelledBy="t-pj" style={{ height: 340 }}>
          <CardHeader id="t-pj" title="Top projects by spend" sub={`${describeTimeRange(spec)} · ranked by total spend`} action={<MoreLink href="/projects">View all</MoreLink>} />
          <div className="scroll-y sticky-head" style={{ flex: 1, minHeight: 0, marginTop: 12 }}>
            {cost.isLoading ? <SkelRows rows={5} /> : !cost.data?.top_projects.length ? (
              <Empty icon={FolderKanban} title="No project spend yet">Spend appears here once a project sends its first call.</Empty>
            ) : (
              <table>
                <thead><tr><th>Project</th><th className="r">Total spend</th><th>Share of spend</th><th className="r">LLM calls</th><th className="r">Tokens</th><th>Error rate</th></tr></thead>
                <tbody>
                  {cost.data.top_projects.map((p) => {
                    const name = labels[p.dimension];
                    return (
                      <tr key={p.dimension} className="clickable" onClick={() => router.push(`/projects/${p.dimension}`)}>
                        <td>
                          <div className="cell-main">
                            <span className="ico" aria-hidden><Bot className="ic" /></span>
                            <div>{name ? <b>{name}</b> : <b style={{ fontStyle: "italic", fontWeight: 500 }}>Unnamed project</b>}<small>{name ? "Project" : `ID ${shortId(p.dimension)}`}</small></div>
                          </div>
                        </td>
                        <td className="r strong">{usd(p.total_cost_usd)}<div className="sub">{usd(p.total_calls ? p.total_cost_usd / p.total_calls : 0)} / call</div></td>
                        <td><ShareCell fraction={total ? p.total_cost_usd / total : 0} label={share(total ? p.total_cost_usd / total : 0)} /></td>
                        <td className="r">{compact(p.total_calls)}</td>
                        <td className="r">{compact(p.total_tokens)}</td>
                        <td><span className={`sdot ${p.error_rate > 5 ? "bad" : "ok"}`}><i aria-hidden />{pct(p.error_rate, p.error_rate ? 2 : 0)}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          <div className="card-foot"><span>{cost.data?.top_projects.length ?? 0} projects with spend</span><span>Sorted by spend</span></div>
        </Card>

        <Card labelledBy="t-live" style={{ height: 340 }}>
          <CardHeader id="t-live" title="Live activity" bordered
            sub={traces.data ? <span className="row" style={{ gap: 14 }}><span>Spans <b className="num" style={{ color: "var(--text)" }}>{compact(traces.data.total)}</b></span><span>Showing latest {traces.data.items.length}</span></span> : "Recent spans"}
            action={<span className="pill pill-accent"><i className="live" aria-hidden />Live</span>} />
          {traces.isError ? <div className="card-b"><ErrorState error={traces.error} compact onRetry={() => traces.refetch()} /></div>
            : traces.isLoading ? <SkelRows rows={6} />
            : <SpanFeed spans={traces.data?.items ?? []} />}
          <div className="card-foot"><span>Most recent first · updates every 15s</span><MoreLink href="/traces">View all traces</MoreLink></div>
        </Card>
      </div>
    </>
  );
}
