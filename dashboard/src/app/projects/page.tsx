"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { FolderKanban, Plus, Search, Wallet, Zap } from "lucide-react";
import { ProjectForm } from "@/components/ProjectForm";
import { Card, CardHeader, Empty, ErrorState, Kpi, PageHead, Pill, ShareCell, SkelRows } from "@/components/ui";
import { useProjects } from "@/lib/api";
import { compact, day, share, usd } from "@/lib/format";
import { projectLabels } from "@/lib/projects";

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
  const calls = items.reduce((a, p) => a + (p.total_calls ?? 0), 0);
  const budgeted = items.filter((p) => p.monthly_budget_usd);
  const over = budgeted.filter((p) => (p.total_cost_usd ?? 0) > (p.monthly_budget_usd ?? Infinity));

  return (
    <>
      <PageHead title="Projects" sub="Every AI application sending telemetry to TrustAI. Spend and calls cover the last 30 days."
        actions={<button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />New project</button>} />

      <section className="kpis" style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Project figures">
        <Kpi icon={FolderKanban} label="Active projects" value={isLoading ? "—" : compact(data?.total)} foot={`${items.filter((p) => (p.total_calls ?? 0) > 0).length} sent calls in the last 30 days`} />
        <Kpi icon={Wallet} label="Spend · 30 days" value={isLoading ? "—" : usd(spend)} foot="Across all projects" />
        <Kpi icon={Zap} label="AI calls · 30 days" value={isLoading ? "—" : compact(calls)} foot={calls ? `${usd(spend / calls)} per call on average` : "No calls yet"} />
        <Kpi icon={Wallet} label="Over budget" tone={over.length ? "bad" : undefined} value={isLoading ? "—" : `${over.length}`} foot={`${budgeted.length} of ${items.length} projects have a monthly budget`} />
      </section>

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
