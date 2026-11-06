"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Gauge, Swords, Target, TriangleAlert } from "lucide-react";
import { EvalBadge, TrustScore } from "@/components/gov";
import { StartEvalModal } from "@/components/GovModals";
import { Card, CardHeader, ChipSelect, Empty, ErrorState, Kpi, PageHead, SkelRows } from "@/components/ui";
import { EVALUATION_STATUSES, useAgentIndex, useEvaluations } from "@/lib/governance";
import { ago, humanize } from "@/lib/format";

export default function EvaluationsPage() {
  const router = useRouter();
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(false);
  const evals = useEvaluations({ status: status || undefined });
  const all = useEvaluations();
  const index = useAgentIndex();
  const items = evals.data ?? [];
  const done = (all.data ?? []).filter((e) => e.status === "completed");
  const avg = done.length ? done.reduce((a, e) => a + (e.trust_score ?? 0), 0) / done.length : null;
  const passing = done.filter((e) => e.summary.meets_threshold).length;
  const fpr = done.filter((e) => e.summary.false_positive_rate_pct != null);
  const avgFp = fpr.length ? fpr.reduce((a, e) => a + (e.summary.false_positive_rate_pct ?? 0), 0) / fpr.length : null;

  return (
    <>
      <PageHead title="Red-team" sub="Attack each agent with generated jailbreaks, prompt injections and data-leak attempts, plus harmless prompts to catch over-blocking."
        actions={<>
          <ChipSelect label="Status" value={status} onChange={setStatus} options={[{ value: "", label: "All" }, ...EVALUATION_STATUSES.map((s) => ({ value: s, label: humanize(s) }))]} />
          <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Swords className="ic" aria-hidden />New run</button>
        </>} />

      <section className="kpis" style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Red-team figures">
        <Kpi icon={Swords} label="Runs" value={all.isLoading ? "—" : String(all.data?.length ?? 0)} foot={`${(all.data ?? []).filter((e) => e.status === "running" || e.status === "queued").length} in progress`} />
        <Kpi icon={Gauge} label="Average trust score" value={avg != null ? avg.toFixed(1) : "—"} foot={`Across ${done.length} completed runs`} />
        <Kpi icon={Target} label="Met the pass mark" value={all.isLoading ? "—" : `${passing} of ${done.length}`} foot="Runs at or above their threshold" />
        <Kpi icon={TriangleAlert} label="Over-blocking" tone={avgFp != null && avgFp > 10 ? "bad" : undefined} value={avgFp != null ? `${avgFp.toFixed(1)}%` : "—"} foot="Harmless prompts wrongly refused" />
      </section>

      <Card labelledBy="t-ev">
        <CardHeader id="t-ev" title="Runs" sub="Newest first · refreshes while runs are in progress" />
        <div style={{ marginTop: 12 }}>
          {evals.isError ? <div className="card-b"><ErrorState error={evals.error} onRetry={() => evals.refetch()} /></div> : evals.isLoading ? <SkelRows rows={6} /> : !items.length ? (
            <Empty icon={Swords} title="No runs yet" action={<button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>Start a run</button>}>Red-teaming gives each agent a trust score for its release gate.</Empty>
          ) : (
            <div className="scroll-x"><table>
              <thead><tr><th>Agent</th><th>Status</th><th>Trust score</th><th className="r">Attacks blocked</th><th className="r">Over-blocked</th><th>Weakest area</th><th className="r">Prompts</th><th className="r">Started</th></tr></thead>
              <tbody>{items.map((e) => {
                const weak = e.summary.weakest_categories?.[0];
                return (
                  <tr key={e.id} className="clickable" onClick={() => router.push(`/governance/evaluations/${e.id}`)}>
                    <td><b>{index[e.agent_id]?.name ?? "Agent"}</b><div className="sub">{humanize(e.eval_type)} · by {e.created_by}</div></td>
                    <td><EvalBadge status={e.status} progress={e.progress} total={e.prompts_total} /></td>
                    <td><TrustScore score={e.trust_score} threshold={e.summary.trust_threshold ?? 95} compact /></td>
                    <td className="r">{e.block_rate_pct != null ? `${e.block_rate_pct.toFixed(1)}%` : "—"}</td>
                    <td className="r">{e.summary.false_positive_rate_pct != null ? `${e.summary.false_positive_rate_pct.toFixed(1)}%` : "—"}</td>
                    <td>{weak ? <span className="tag bad">{humanize(weak.category)} · {weak.block_rate_pct.toFixed(0)}%</span> : <span className="muted">—</span>}</td>
                    <td className="r">{e.prompts_total}</td>
                    <td className="r muted">{ago(e.created_at)}</td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          )}
        </div>
      </Card>
      <StartEvalModal open={open} onClose={() => setOpen(false)} onStarted={(e) => router.push(`/governance/evaluations/${e.id}`)} />
    </>
  );
}
