"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ClipboardCheck, FileClock, Gavel, Plus, ShieldAlert } from "lucide-react";
import { AssessmentBadge, DecisionBadge, TierBadge, TIER_LABEL } from "@/components/gov";
import { Card, CardHeader, Empty, ErrorState, Kpi, Modal, PageHead, SkelRows, Tabs, errMsg, useToast } from "@/components/ui";
import { useAgentIndex, useAgents, useAssessments, useCreateAssessment, useRiskTemplate } from "@/lib/governance";
import { ago, when } from "@/lib/format";

type F = "" | "draft" | "classified" | "decided";
const TIER_C: Record<number, string> = { 1: "var(--accent)", 2: "var(--c2)", 3: "var(--c3)", 4: "var(--danger)" };

export default function RiskPage() {
  const router = useRouter();
  const [f, setF] = useState<F>("");
  const [open, setOpen] = useState(false);
  const all = useAssessments();
  const tpl = useRiskTemplate();
  const index = useAgentIndex();
  const items = (all.data ?? []).filter((a) => !f || a.status === f || (f === "draft" && a.status === "submitted"));
  const count = (s: string) => (all.data ?? []).filter((a) => a.status === s).length;
  const decided = (all.data ?? []).filter((a) => a.status === "decided");
  const highRisk = (all.data ?? []).filter((a) => (a.risk_tier ?? 0) >= 3).length;

  return (
    <>
      <PageHead title="Risk assessments" sub={`Questionnaire mapped to ${tpl.data?.frameworks.join(", ") ?? "EU AI Act, NIST AI RMF and ISO/IEC 42001"}. Tiers drive the controls an agent must meet.`}
        actions={<button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />New assessment</button>} />

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Assessment figures">
        <Kpi icon={FileClock} label="Drafts" value={all.isLoading ? "—" : String(count("draft") + count("submitted"))} foot="Being filled in" />
        <Kpi icon={Gavel} label="Needs decision" tone={count("classified") ? "wait" : undefined} value={all.isLoading ? "—" : String(count("classified"))} foot="Classified, waiting on a person" />
        <Kpi icon={ClipboardCheck} label="Decided" value={all.isLoading ? "—" : String(decided.length)} foot={`${decided.filter((a) => a.decision === "rejected").length} rejected`} />
        <Kpi icon={ShieldAlert} label="High or critical" tone={highRisk ? "bad" : undefined} value={all.isLoading ? "—" : String(highRisk)} foot="Tier 3 or 4 — extra controls apply" />
      </section>

      <div className="split-wide" style={{ alignItems: "start" }}>
        <Card labelledBy="t-as">
          <CardHeader id="t-as" title="Assessments" sub="Newest first" />
          <div style={{ padding: "6px 18px 0" }}>
            <Tabs label="Status" value={f} onChange={setF} tabs={[
              { id: "", label: "All", count: all.data?.length ?? null }, { id: "draft", label: "Drafts", count: count("draft") + count("submitted") },
              { id: "classified", label: "Needs decision", count: count("classified") }, { id: "decided", label: "Decided", count: decided.length },
            ]} />
          </div>
          {all.isError ? <div className="card-b"><ErrorState error={all.error} onRetry={() => all.refetch()} /></div> : all.isLoading ? <SkelRows rows={6} /> : !items.length ? (
            <Empty icon={ClipboardCheck} title="Nothing here">No assessments with this status.</Empty>
          ) : (
            <div className="scroll-x"><table>
              <thead><tr><th>Agent</th><th>Status</th><th>Risk tier</th><th className="r">Score</th><th>Decision</th><th className="r">Updated</th></tr></thead>
              <tbody>{items.map((a) => (
                <tr key={a.id} className="clickable" onClick={() => router.push(`/governance/risk/${a.id}`)}>
                  <td><b>{index[a.agent_id]?.name ?? "Agent"}</b><div className="sub">Started {when(a.created_at)} by {a.created_by}</div></td>
                  <td><AssessmentBadge status={a.status} /></td>
                  <td><TierBadge tier={a.risk_tier} /></td>
                  <td className="r num">{a.risk_score ?? "—"}</td>
                  <td>{a.status === "decided" ? <DecisionBadge decision={a.decision} /> : <span className="muted">—</span>}</td>
                  <td className="r muted">{ago(a.updated_at)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </Card>

        <Card labelledBy="t-tiers">
          <CardHeader id="t-tiers" title="What each tier requires" sub="Controls an agent must meet before release" bordered />
          <div className="card-b" style={{ gap: 14 }}>
            {tpl.isLoading ? <SkelRows rows={6} /> : (tpl.data?.tiers ?? []).map((t) => (
              <div key={t.tier} style={{ display: "grid", gridTemplateColumns: "4px minmax(0,1fr)", gap: 12 }}>
                <i style={{ background: TIER_C[t.tier], borderRadius: 2 }} aria-hidden />
                <div>
                  <b className="small" style={{ fontWeight: 600 }}>Tier {t.tier} · {TIER_LABEL[t.tier]}</b>
                  <ul className="small muted" style={{ margin: "4px 0 0", paddingLeft: 16, listStyle: "disc", lineHeight: 1.6 }}>{t.required_controls.map((c) => <li key={c}>{c}</li>)}</ul>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
      <NewAssessment open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function NewAssessment({ open, onClose }: { open: boolean; onClose: () => void }) {
  const agents = useAgents({ limit: 200 });
  const create = useCreateAssessment();
  const router = useRouter();
  const toast = useToast();
  const [agent, setAgent] = useState("");
  return (
    <Modal open={open} onClose={onClose} title="New risk assessment" sub="Answers are pre-filled from the agent's build facts where possible."
      footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-primary" disabled={!agent || create.isPending} onClick={() => create.mutate({ agent_id: agent }, { onSuccess: (a) => router.push(`/governance/risk/${a.id}`), onError: (e) => toast(errMsg(e), true) })}>{create.isPending ? "Starting…" : "Start"}</button></>}>
      <div className="field"><label htmlFor="na-agent">Agent</label>
        <select id="na-agent" className="select-native" value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="">Choose an agent…</option>
          {(agents.data?.items ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} · {a.external_id}</option>)}
        </select></div>
    </Modal>
  );
}
