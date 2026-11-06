"use client";
import { useMemo, useState } from "react";
import { Coins, DollarSign, Gauge, Layers, Receipt } from "lucide-react";
import { BarChart, MiniBars, SERIES, SEQ, SplitBar } from "@/components/charts";
import { BreakdownRow } from "@/components/blocks";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { Card, CardHeader, ChipSelect, Empty, ErrorState, Kpi, PageHead, Seg, ShareCell, Skel, SkelRows, StatStrip, Tabs } from "@/components/ui";
import { useCostBreakdown, useProjects, type Dim } from "@/lib/api";
import { compact, envName, providerName, share, shortId, usd, usdShort } from "@/lib/format";
import { projectLabels } from "@/lib/projects";
import { fillDays, slices } from "@/lib/series";
import { describeTimeRange, rangePhrase, resolveTimeRange } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

type DimKey = "by_model" | "by_provider" | "by_environment" | "by_project" | "by_agent" | "by_client";
const DIMS: { id: DimKey; label: string; col: string }[] = [
  { id: "by_model", label: "Model", col: "Model" },
  { id: "by_provider", label: "Provider", col: "Provider" },
  { id: "by_environment", label: "Environment", col: "Environment" },
  { id: "by_project", label: "Project", col: "Project" },
  { id: "by_agent", label: "Agent", col: "Agent" },
  { id: "by_client", label: "Client", col: "Client" },
];
type Metric = "cost" | "calls" | "tokens";

export default function CostPage() {
  const { spec, key } = useTimeRange();
  const [project, setProject] = useState("");
  const [env, setEnv] = useState("");
  const [metric, setMetric] = useState<Metric>("cost");
  const [dim, setDim] = useState<DimKey>("by_model");
  const projects = useProjects();
  const all = useCostBreakdown(spec, key);
  const cost = useCostBreakdown(spec, key, { project_id: project || undefined, environment: env || undefined });
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const range = useMemo(() => resolveTimeRange(spec), [spec]);
  const days = useMemo(() => fillDays(cost.data?.time_series ?? [], range.from, range.to), [cost.data, range]);
  const d = cost.data;

  const total = d ? d.by_model.reduce((a, x) => a + x.total_cost_usd, 0) : 0;
  const calls = d ? d.by_model.reduce((a, x) => a + x.total_calls, 0) : 0;
  const tokens = d ? d.by_model.reduce((a, x) => a + x.total_tokens, 0) : 0;
  const tin = d ? d.by_model.reduce((a, x) => a + (x.total_input_tokens ?? 0), 0) : 0;
  const tout = d ? d.by_model.reduce((a, x) => a + (x.total_output_tokens ?? 0), 0) : 0;
  const peak = days.reduce<typeof days[number] | null>((p, x) => (x.cost > (p?.cost ?? 0) ? x : p), null);

  const nameOf = (k: DimKey, id: string) => {
    if (k === "by_provider") return providerName(id);
    if (k === "by_environment") return envName(id);
    if (k === "by_project") return labels[id] ?? (id === "None" ? "Not set" : `Unnamed · ${shortId(id)}`);
    if (id === "None" || id === "null") return "Not set";
    return k === "by_agent" || k === "by_client" ? shortId(id, 12) : id;
  };
  const rows: Dim[] = d?.[dim] ?? [];
  const palette = dim === "by_environment" ? SEQ : SERIES;
  const envOptions = (all.data?.by_environment ?? []).map((e) => ({ value: e.dimension === "None" ? "" : e.dimension, label: envName(e.dimension) })).filter((o) => o.value);
  const loading = cost.isLoading;

  return (
    <>
      <PageHead
        title="Cost insights"
        sub={`Where AI spend comes from and what it buys, for the ${rangePhrase(spec)}`}
        actions={<>
          <ChipSelect label="Project" value={project} onChange={setProject} options={[{ value: "", label: "All projects" }, ...(projects.data?.items ?? []).map((p) => ({ value: p.id, label: labels[p.id] ?? p.name }))]} />
          <ChipSelect label="Environment" value={env} onChange={setEnv} options={[{ value: "", label: "All environments" }, ...envOptions]} />
          <TimeRangePicker />
        </>}
      />

      {cost.isError ? <Card><ErrorState error={cost.error} onRetry={() => cost.refetch()} /></Card> : (
        <>
          <section className="kpis" style={{ ["--cols" as string]: 5 } as React.CSSProperties} aria-label="Cost figures">
            <Kpi icon={DollarSign} label="Total spend" value={loading ? <Skel w={90} h={22} /> : usd(total)} vis={<MiniBars values={days.slice(-9).map((x) => x.cost)} />} foot={`${compact(calls)} calls · ${describeTimeRange(spec)}`} />
            <Kpi icon={Receipt} label="Average per day" value={loading ? <Skel w={80} h={22} /> : usd(days.length ? total / days.length : 0)} foot={peak ? `Peak ${peak.label} · ${usd(peak.cost)}` : "No spend yet"} />
            <Kpi icon={Coins} label="Cost per call" value={loading ? <Skel w={80} h={22} /> : usd(calls ? total / calls : 0)} foot="Across every model and agent" />
            <Kpi icon={Gauge} label="Cost per 1K tokens" value={loading ? <Skel w={80} h={22} /> : usd(tokens ? (total / tokens) * 1000 : 0)} foot={`${compact(tokens)} tokens in total`} />
            <Kpi icon={Layers} label="Token mix" value={loading ? <Skel w={80} h={22} /> : compact(tokens)}
              vis={tin || tout ? <SplitBar parts={[{ value: tin, color: "var(--accent)" }, { value: tout, color: "var(--accent-line)" }]} /> : undefined}
              foot={tin || tout ? `In ${compact(tin)} · Out ${compact(tout)}` : "Input / output split not reported"} />
          </section>

          <div className="split-l">
            <Card labelledBy="t-trend">
              <CardHeader id="t-trend" title={metric === "cost" ? "Spend over time" : metric === "calls" ? "Calls over time" : "Tokens over time"}
                sub={`Per day · ${describeTimeRange(spec)}`}
                action={<Seg small label="Metric" value={metric} onChange={setMetric} options={[["cost", "Spend"], ["calls", "Calls"], ["tokens", "Tokens"]] as const} />} />
              <div style={{ padding: "14px 18px 0" }}>
                <StatStrip items={[
                  ["Total", metric === "cost" ? usd(total) : compact(metric === "calls" ? calls : tokens)],
                  ["Average per day", metric === "cost" ? usd(days.length ? total / days.length : 0) : compact(days.length ? (metric === "calls" ? calls : tokens) / days.length : 0)],
                  ["Days with activity", `${days.filter((x) => x.calls > 0 || x.cost > 0).length} of ${days.length}`],
                ]} />
              </div>
              <div style={{ flex: 1, minHeight: 220, margin: "14px 18px" }}>
                {loading ? <Skel h={220} /> : (
                  <BarChart height="fill" ariaLabel={`${metric} per day`} emphasis="max"
                    data={days.map((x) => ({ label: x.label, long: x.long, value: metric === "cost" ? x.cost : metric === "calls" ? x.calls : x.tokens,
                      extra: metric === "cost" ? [{ name: "AI calls", value: compact(x.calls) }] : [{ name: "Spend", value: usd(x.cost) }] }))}
                    fmt={(v) => (metric === "cost" ? usd(v) : compact(v))} fmtAxis={(v) => (metric === "cost" ? usdShort(v) : compact(v))} />
                )}
              </div>
            </Card>

            <Card labelledBy="t-bk">
              <CardHeader id="t-bk" title="Where spend goes" sub={`Share of ${usd(total)}`} />
              {loading ? <SkelRows rows={6} /> : (
                <div className="bk">
                  <BreakdownRow title="By model" slices={slices(d?.by_model, "model")} />
                  <BreakdownRow title="By provider" slices={slices(d?.by_provider, "provider")} />
                  <BreakdownRow title="By environment" slices={slices(d?.by_environment, "environment")} />
                </div>
              )}
            </Card>
          </div>

          <Card labelledBy="t-table">
            <CardHeader id="t-table" title="Spend breakdown" sub="Every dimension the rollups track. Click a tab to regroup." />
            <div style={{ padding: "6px 18px 0" }}>
              <Tabs label="Group by" value={dim} onChange={setDim} tabs={DIMS.map((x) => ({ id: x.id, label: x.label, count: d ? d[x.id].length : null }))} />
            </div>
            {loading ? <SkelRows rows={5} /> : !rows.length ? (
              <Empty icon={DollarSign} title="Nothing to break down">No spend was recorded for this selection.</Empty>
            ) : (
              <div className="scroll-x">
                <table>
                  <thead><tr>
                    <th>{DIMS.find((x) => x.id === dim)?.col}</th><th className="r">Spend</th><th>Share of spend</th>
                    <th className="r">Calls</th><th className="r">Tokens</th><th className="r">Input</th><th className="r">Output</th><th className="r">Cost / call</th><th className="r">Cost / 1K tokens</th>
                  </tr></thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={r.dimension + i}>
                        <td><span className="chip" title={r.dimension}><i style={{ background: palette[i] ?? "var(--c5)" }} aria-hidden /><span className="ellipsis">{nameOf(dim, r.dimension)}</span></span></td>
                        <td className="r strong">{usd(r.total_cost_usd)}</td>
                        <td><ShareCell fraction={total ? r.total_cost_usd / total : 0} color={palette[i] ?? "var(--c5)"} label={share(total ? r.total_cost_usd / total : 0)} /></td>
                        <td className="r">{compact(r.total_calls)}</td>
                        <td className="r">{compact(r.total_tokens)}</td>
                        <td className="r muted">{r.total_input_tokens ? compact(r.total_input_tokens) : "—"}</td>
                        <td className="r muted">{r.total_output_tokens ? compact(r.total_output_tokens) : "—"}</td>
                        <td className="r">{usd(r.total_calls ? r.total_cost_usd / r.total_calls : 0)}</td>
                        <td className="r">{usd(r.total_tokens ? (r.total_cost_usd / r.total_tokens) * 1000 : 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
