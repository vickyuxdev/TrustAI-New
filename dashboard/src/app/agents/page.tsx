"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Clock, DollarSign, Search, ShieldCheck } from "lucide-react";
import { TimeRangePicker } from "@/components/shell/TimeRangePicker";
import { Card, CardHeader, Empty, ErrorState, Kpi, PageHead, ShareCell, SkelRows } from "@/components/ui";
import { useObservedAgents } from "@/lib/api";
import { ago, compact, ms, pct, share, usd } from "@/lib/format";
import { rangePhrase } from "@/lib/timeRange";
import { useTimeRange } from "@/lib/useTimeRange";

export default function AgentsPage() {
  const router = useRouter();
  const { spec, key } = useTimeRange();
  const [q, setQ] = useState("");
  const { data, isLoading, isError, error, refetch } = useObservedAgents(spec, key);
  const items = useMemo(() => data?.items ?? [], [data]);
  const list = items.filter((a) => `${a.name} ${a.project_name ?? ""} ${a.client_name ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  const spend = items.reduce((a, x) => a + x.total_cost_usd, 0);
  const calls = items.reduce((a, x) => a + x.total_calls, 0);
  const errs = items.reduce((a, x) => a + x.error_rate * x.total_calls, 0);
  const slowest = items.reduce<typeof items[number] | null>((s, x) => ((x.avg_duration_ms ?? 0) > (s?.avg_duration_ms ?? 0) ? x : s), null);

  return (
    <>
      <PageHead title="Agents" sub={`Agents discovered from telemetry in the ${rangePhrase(spec)}. One row per agent and project.`} actions={<TimeRangePicker />} />
      <section className="kpis" style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Agent figures">
        <Kpi icon={Bot} label="Active agents" value={isLoading ? "—" : compact(items.length)} foot={`${new Set(items.map((a) => a.project_id)).size} projects`} />
        <Kpi icon={DollarSign} label="Agent spend" value={isLoading ? "—" : usd(spend)} foot={`${compact(calls)} agent runs`} />
        <Kpi icon={ShieldCheck} label="Run error rate" tone={calls && errs / calls > 0.05 ? "bad" : undefined} value={isLoading ? "—" : pct(calls ? (errs / calls) * 100 : 0)} foot={`${compact(Math.round(errs))} failed runs`} />
        <Kpi icon={Clock} label="Slowest agent" value={isLoading ? "—" : ms(slowest?.avg_duration_ms)} foot={slowest ? `${slowest.name} · average run` : "No runs yet"} />
      </section>
      <Card labelledBy="t-ag">
        <CardHeader id="t-ag" title="All agents" sub="Click an agent to see its traces"
          action={<label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Search agents</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search agents or projects" /></label>} />
        <div style={{ marginTop: 12 }}>
          {isError ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading ? <SkelRows rows={6} /> : !list.length ? (
            <Empty icon={Bot} title={q ? "No agents match" : "No agent runs yet"}>
              {q ? "Try another name." : "Agents show up when spans with kind “agent” arrive, for example from @trustai.agent in the SDK."}
            </Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead><tr><th>Agent</th><th>Project</th><th className="r">Runs</th><th className="r">Tokens</th><th className="r">Spend</th><th>Share of spend</th><th className="r">Avg. duration</th><th>Error rate</th><th className="r">Last active</th></tr></thead>
                <tbody>
                  {list.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => router.push(`/traces?agent=${encodeURIComponent(a.name)}${a.project_id ? `&project=${a.project_id}` : ""}`)}>
                      <td><div className="cell-main"><span className="ico" aria-hidden><Bot className="ic" /></span><div><b>{a.name}</b><small>{a.span_name ?? a.slug}</small></div></div></td>
                      <td>{a.project_name ?? <span className="muted">Unassigned</span>}{a.client_name && <div className="sub">{a.client_name}</div>}</td>
                      <td className="r">{compact(a.total_calls)}</td>
                      <td className="r">{compact(a.total_tokens ?? 0)}</td>
                      <td className="r strong">{usd(a.total_cost_usd)}</td>
                      <td><ShareCell fraction={spend ? a.total_cost_usd / spend : 0} label={share(spend ? a.total_cost_usd / spend : 0)} /></td>
                      <td className="r">{ms(a.avg_duration_ms)}</td>
                      <td><span className={`sdot ${a.error_rate > 0.05 ? "bad" : "ok"}`}><i aria-hidden />{pct(a.error_rate * 100, a.error_rate ? 2 : 0)}</span></td>
                      <td className="r muted">{ago(a.last_active)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </>
  );
}
