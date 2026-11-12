"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bot, Library, Plus, Search, ShieldCheck, ShieldX, Wrench } from "lucide-react";
import { Ring, Segments, Sparkline } from "@/components/charts";
import { LifecycleBadge, LIFE_LABEL, TierBadge, TrustScore } from "@/components/gov";
import { Card, CardHeader, ChipSelect, Empty, ErrorState, Kpi, Modal, PageHead, SkelRows, errMsg, useToast } from "@/components/ui";
import { LIFECYCLE_STATUSES, useAgents, useOnboardAgent, useOverview } from "@/lib/governance";
import { ago, compact } from "@/lib/format";

const PAGE = 25;
const slug = (s: string) => s.toLowerCase().trim().replace(/[^a-z0-9._:-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 120);

export default function RegistryPage() {
  const router = useRouter();
  const [status, setStatus] = useState("");
  const [tier, setTier] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(false);
  const agents = useAgents({ status: status || undefined, risk_tier: tier || undefined, search: q || undefined, limit: PAGE, offset });
  const ov = useOverview();
  const o = ov.data;
  const items = agents.data?.items ?? [];
  const total = agents.data?.total ?? 0;
  const all = useAgents({ limit: 200 });
  const reg = useMemo(() => all.data?.items ?? [], [all.data]);
  const [now] = useState(() => Date.now());
  const st = (k: string) => o?.agents_by_status[k as keyof typeof o.agents_by_status] ?? 0;
  const live = st("deployed") + st("approved");
  const blocked = st("suspended");
  const regTotal = o?.agents_total ?? reg.length;
  const onboarding = st("registered") + st("onboarded");
  // Registry size at the end of each of the last 12 weeks.
  const growth = useMemo(() => Array.from({ length: 12 }, (_, k) => reg.filter((a) => +new Date(a.created_at) <= now - (11 - k) * 7 * 864e5).length), [reg, now]);
  const added30 = reg.filter((a) => +new Date(a.created_at) > now - 30 * 864e5).length;
  const suspended = reg.filter((a) => a.lifecycle_status === "suspended");
  const belowBar = reg.filter((a) => a.lifecycle_status === "evaluated" && a.trust_score != null && a.trust_score < 95).length;

  return (
    <>
      <PageHead title="Agent registry" sub="Every agent the AI factory has built, with its lifecycle stage, risk tier and trust score."
        actions={<button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />Onboard agent</button>} />

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Registry figures">
        <Kpi icon={Library} label="Registered agents" value={ov.isLoading ? "—" : compact(regTotal)}
          vis={reg.length > 1 ? <Sparkline values={growth} width={88} height={30} /> : undefined}
          foot={<span>{added30 ? <><b className="kpi-up">+{added30}</b> in the last 30 days · </> : null}{onboarding} still onboarding</span>} />
        <Kpi icon={ShieldCheck} label="Cleared for production" value={ov.isLoading ? "—" : <>{live}<small className="kpi-of"> / {regTotal}</small></>}
          vis={regTotal ? <Ring size={34} stroke={5} ariaLabel={`${live} of ${regTotal} cleared`}
            slices={[{ name: "Deployed", value: st("deployed"), color: "var(--accent)" }, { name: "Approved", value: st("approved"), color: "var(--g2)" }, { name: "Other", value: regTotal - live, color: "var(--line-2)" }]} /> : undefined}
          foot={<span><Dot c="var(--accent)" />{st("deployed")} deployed<Dot c="var(--g2)" />{st("approved")} approved · {regTotal ? Math.round((live / regTotal) * 100) : 0}% of registry</span>} />
        <Kpi icon={Wrench} label="In review" value={ov.isLoading ? "—" : String(st("assessed") + st("evaluated"))}
          vis={st("assessed") + st("evaluated") ? <div style={{ width: 88 }}><Segments height={8} ariaLabel="Agents in review by step" parts={[
            { value: st("assessed"), color: "var(--g1)", label: "Risk-assessed" }, { value: st("evaluated"), color: "var(--g3)", label: "Red-teamed" }]} /></div> : undefined}
          foot={<span><Dot c="var(--g1)" />{st("assessed")} risk-assessed<Dot c="var(--g3)" />{st("evaluated")} red-teamed{belowBar ? ` · ${belowBar} below 95` : ""}</span>} />
        <Kpi icon={ShieldX} label="Suspended" tone={blocked ? "bad" : undefined} value={ov.isLoading ? "—" : blocked ? <span style={{ color: "var(--danger)" }}>{blocked}</span> : "0"}
          vis={suspended[0]?.trust_score != null ? <span className="kpi-bar" title={`Trust ${suspended[0].trust_score.toFixed(1)} of 95`}><i style={{ width: `${Math.max(0, (suspended[0].trust_score - 50) / 50) * 100}%` }} /><em /></span> : undefined}
          foot={suspended.length ? <span>{suspended.slice(0, 2).map((a, i) => <span key={a.id}>{i ? ", " : ""}<Link className="kpi-link" href={`/governance/agents/${a.id}`}>{a.name}</Link></span>)}{suspended[0].trust_score != null ? ` · trust ${suspended[0].trust_score.toFixed(1)}, bar is 95` : ""}</span> : "No agents blocked from serving traffic"} />
      </section>

      <Card labelledBy="t-reg">
        <CardHeader id="t-reg" title="Agents" sub={`${total} matching`}
          action={<div className="filterbar">
            <label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Search agents</span><input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="Search name, ID or owner" /></label>
            <ChipSelect label="Stage" value={status} onChange={(v) => { setStatus(v); setOffset(0); }} options={[{ value: "", label: "All" }, ...LIFECYCLE_STATUSES.map((s) => ({ value: s, label: LIFE_LABEL[s] }))]} />
            <ChipSelect label="Tier" value={tier} onChange={(v) => { setTier(v); setOffset(0); }} options={[{ value: "", label: "All" }, { value: "1", label: "1 · Minimal" }, { value: "2", label: "2 · Limited" }, { value: "3", label: "3 · High" }, { value: "4", label: "4 · Critical" }]} />
          </div>} />
        <div style={{ marginTop: 12 }}>
          {agents.isError ? <ErrorState error={agents.error} onRetry={() => agents.refetch()} /> : agents.isLoading ? <SkelRows rows={8} /> : !items.length ? (
            <Empty icon={Bot} title={q || status || tier ? "No agents match" : "No agents yet"}
              action={!(q || status || tier) && <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />Onboard your first agent</button>}>
              {q || status || tier ? "Try clearing a filter." : "Onboard an agent to start its risk assessment, red-teaming and deployment gate."}
            </Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead><tr><th>Agent</th><th>Stage</th><th>Risk tier</th><th>Trust score</th><th>Model</th><th className="r">Tools</th><th className="r">Policies</th><th>Owner</th><th className="r">Updated</th></tr></thead>
                <tbody>
                  {items.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => router.push(`/governance/agents/${a.id}`)}>
                      <td><div className="cell-main"><span className="ico" aria-hidden><Bot className="ic" /></span><div><b>{a.name}</b><small>{a.external_id} · v{a.version}</small></div></div></td>
                      <td><LifecycleBadge status={a.lifecycle_status} /></td>
                      <td><TierBadge tier={a.risk_tier} /></td>
                      <td><TrustScore score={a.trust_score} compact /></td>
                      <td className="muted">{a.model ?? "—"}</td>
                      <td className="r">{a.tools.length}</td>
                      <td className="r">{a.policy_ids.length}</td>
                      <td>{a.owner ?? a.built_by ?? <span className="muted">—</span>}</td>
                      <td className="r muted">{ago(a.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {total > PAGE && (
          <div className="card-foot">
            <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
            <span className="row">
              <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
              <button type="button" className="btn btn-sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
            </span>
          </div>
        )}
      </Card>

      <OnboardModal open={open} onClose={() => setOpen(false)} onDone={(id) => router.push(`/governance/agents/${id}`)} />
    </>
  );
}

const Dot = ({ c }: { c: string }) => <i className="kpi-dot" style={{ background: c }} aria-hidden />;

function OnboardModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (id: string) => void }) {
  const onboard = useOnboardAgent();
  const toast = useToast();
  const [f, setF] = useState({ name: "", external_id: "", description: "", version: "1.0.0", model: "", built_by: "", client: "", autonomy_level: "", endpoint: "", tags: "", baseline: true });
  const [idTouched, setIdTouched] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f, v: string | boolean) => setF((x) => ({ ...x, [k]: v, ...(k === "name" && !idTouched ? { external_id: slug(String(v)) } : {}) }));

  const submit = async () => {
    setErr(null);
    if (!f.name.trim()) return setErr("Give the agent a name.");
    if (!/^[A-Za-z0-9._:-]+$/.test(f.external_id)) return setErr("The agent ID can use letters, numbers, dots, dashes, underscores and colons.");
    if (f.endpoint && !/^https?:\/\//.test(f.endpoint)) return setErr("The endpoint must start with http:// or https://.");
    try {
      const a = await onboard.mutateAsync({
        name: f.name.trim(), external_id: f.external_id, description: f.description || null, version: f.version || "1.0.0",
        model: f.model || null, built_by: f.built_by || null, client: f.client || null, autonomy_level: f.autonomy_level || null,
        endpoint: f.endpoint || null, tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean), attach_baseline_policy: f.baseline,
      });
      toast(`${a.name} onboarded`);
      onClose();
      onDone(a.id);
    } catch (e) { setErr(errMsg(e)); }
  };

  return (
    <Modal open={open} onClose={onClose} wide title="Onboard an agent" sub="Registers the agent so it can be risk-assessed, red-teamed and gated. Re-onboarding the same ID updates it."
      footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button><button type="button" className="btn btn-primary" disabled={onboard.isPending} onClick={submit}>{onboard.isPending ? "Onboarding…" : "Onboard agent"}</button></>}>
      <div className="field-row">
        <div className="field"><label htmlFor="ob-name">Name</label><input id="ob-name" className="input" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Claims triage assistant" /></div>
        <div className="field"><label htmlFor="ob-id">Agent ID</label><input id="ob-id" className="input" value={f.external_id} onChange={(e) => { setIdTouched(true); set("external_id", e.target.value); }} placeholder="claims-triage" /></div>
      </div>
      <div className="field"><label htmlFor="ob-desc">What it does</label><textarea id="ob-desc" className="textarea" rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} placeholder="Reads incoming claims and routes them to the right adjuster." /></div>
      <div className="field-row">
        <div className="field"><label htmlFor="ob-model">Model</label><input id="ob-model" className="input" value={f.model} onChange={(e) => set("model", e.target.value)} placeholder="gpt-4o" /></div>
        <div className="field"><label htmlFor="ob-ver">Version</label><input id="ob-ver" className="input" value={f.version} onChange={(e) => set("version", e.target.value)} /></div>
        <div className="field"><label htmlFor="ob-aut">Autonomy</label>
          <select id="ob-aut" className="select-native" value={f.autonomy_level} onChange={(e) => set("autonomy_level", e.target.value)}>
            <option value="">Not set</option><option value="assistive">Assistive — a person acts</option><option value="supervised">Supervised — a person approves</option><option value="autonomous">Autonomous — acts on its own</option>
          </select></div>
      </div>
      <div className="field-row">
        <div className="field"><label htmlFor="ob-by">Built by</label><input id="ob-by" className="input" value={f.built_by} onChange={(e) => set("built_by", e.target.value)} placeholder="AI Factory" /></div>
        <div className="field"><label htmlFor="ob-cl">Client</label><input id="ob-cl" className="input" value={f.client} onChange={(e) => set("client", e.target.value)} placeholder="Optional" /></div>
        <div className="field"><label htmlFor="ob-tags">Tags</label><input id="ob-tags" className="input" value={f.tags} onChange={(e) => set("tags", e.target.value)} placeholder="claims, internal" /></div>
      </div>
      <div className="field"><label htmlFor="ob-ep">Chat endpoint (optional)</label><input id="ob-ep" className="input" value={f.endpoint} onChange={(e) => set("endpoint", e.target.value)} placeholder="https://claims-agent.internal/chat" />
        <span className="small muted">Takes {"{\"message\"}"} and returns {"{\"response\"}"}. Needed for connection tests and red-team runs.</span></div>
      <label className="check"><input type="checkbox" checked={f.baseline} onChange={(e) => set("baseline", e.target.checked)} />Attach the baseline safety policy</label>
      {err && <div className="banner bad" role="alert">{err}</div>}
    </Modal>
  );
}
