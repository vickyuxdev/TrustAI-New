"use client";
import { useState } from "react";
import { Cpu, KeyRound, Network, Power } from "lucide-react";
import { AgentLink } from "@/components/gov";
import { Card, CardHeader, Empty, ErrorState, Kpi, Modal, PageHead, Pill, Seg, SkelRows, errMsg, useToast } from "@/components/ui";
import { useAgentIndex, useDeployments, useGatewayModels, useRevokeGateway, type GatewayDeploymentRow } from "@/lib/governance";
import { ago, when } from "@/lib/format";

export default function GatewayPage() {
  const [show, setShow] = useState<"active" | "all">("active");
  const deps = useDeployments(show === "active");
  const all = useDeployments(false);
  const models = useGatewayModels();
  const index = useAgentIndex();
  const revoke = useRevokeGateway();
  const toast = useToast();
  const [target, setTarget] = useState<GatewayDeploymentRow | null>(null);
  const items = deps.data ?? [];
  const active = (all.data ?? []).filter((d) => d.status === "active");
  const revoked = (all.data ?? []).filter((d) => d.status === "revoked").length;

  return (
    <>
      <PageHead title="AI gateway" sub="Agents that passed the deployment gate get a scoped gateway key. Every call through it runs the agent's policies, and revoking the key cuts access instantly." />
      <section className="kpis" style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Gateway figures">
        <Kpi icon={Network} label="Active deployments" value={all.isLoading ? "—" : String(active.length)} foot={(() => { const n = new Set(active.map((d) => d.agent_id)).size; return `${n} ${n === 1 ? "agent" : "agents"} live`; })()} />
        <Kpi icon={Power} label="Revoked" value={all.isLoading ? "—" : String(revoked)} foot="Keys that no longer work" />
        <Kpi icon={Cpu} label="Models served" value={models.isLoading ? "—" : String(models.data?.models.length ?? 0)} foot={(models.data?.models ?? []).slice(0, 3).join(", ") || "—"} />
        <Kpi icon={KeyRound} label="Latest deployment" value={active[0] ? ago(active[0].created_at) : "—"} foot={active[0] ? `${index[active[0].agent_id]?.name ?? "Agent"} · ${active[0].model}` : "Nothing deployed yet"} />
      </section>

      <div className="split-wide" style={{ alignItems: "start" }}>
        <Card labelledBy="t-dep">
          <CardHeader id="t-dep" title="Deployments" sub="Deploy from an agent's Gateway tab once its gate is open"
            action={<Seg small label="Show" value={show} onChange={setShow} options={[["active", "Active"], ["all", "All"]] as const} />} />
          <div style={{ marginTop: 12 }}>
            {deps.isError ? <div className="card-b"><ErrorState error={deps.error} onRetry={() => deps.refetch()} /></div> : deps.isLoading ? <SkelRows rows={5} /> : !items.length ? (
              <Empty icon={Network} title="No deployments">Approved agents appear here once deployed behind the gateway.</Empty>
            ) : (
              <div className="scroll-x"><table>
                <thead><tr><th>Agent</th><th>Model</th><th>Allowed models</th><th>Key</th><th>Status</th><th>Deployed</th><th className="r"><span className="sr">Actions</span></th></tr></thead>
                <tbody>{items.map((d) => (
                  <tr key={d.deployment_id}>
                    <td><AgentLink agent={index[d.agent_id]} id={d.agent_id} /></td>
                    <td>{d.model}</td>
                    <td className="muted">{d.allowed_models.join(", ") || "—"}</td>
                    <td className="muted num">{d.key_prefix}…</td>
                    <td><Pill tone={d.status === "active" ? "accent" : undefined} dot>{d.status === "active" ? "Active" : "Revoked"}</Pill></td>
                    <td className="muted" title={when(d.created_at)}>{ago(d.created_at)} · {d.deployed_by}{d.revoked_at && <div className="sub">Revoked {ago(d.revoked_at)}</div>}</td>
                    <td className="r">{d.status === "active" && <button type="button" className="btn btn-sm btn-danger" onClick={() => setTarget(d)}><Power className="ic" aria-hidden />Revoke</button>}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </div>
        </Card>
        <Card labelledBy="t-mod">
          <CardHeader id="t-mod" title="Models on the gateway" sub="Agents can only call these" bordered />
          <div className="card-b">
            {models.isError ? <ErrorState error={models.error} compact /> : models.isLoading ? <SkelRows rows={4} /> : !models.data?.models.length ? <p className="small muted" style={{ margin: 0 }}>No models configured on the gateway.</p> : (
              <ul className="list">{models.data.models.map((m) => (
                <li key={m}><span className="row"><Cpu className="ic" style={{ width: 14, height: 14, color: "var(--text-3)" }} aria-hidden /><b>{m}</b></span><span className="small muted">{(() => { const n = active.filter((d) => d.model === m).length; return `${n} ${n === 1 ? "agent" : "agents"}`; })()}</span></li>
              ))}</ul>
            )}
          </div>
        </Card>
      </div>

      <Modal open={!!target} onClose={() => setTarget(null)} title="Revoke gateway access?" sub="The key stops working immediately."
        footer={<><button type="button" className="btn" onClick={() => setTarget(null)}>Cancel</button>
          <button type="button" className="btn btn-danger" disabled={revoke.isPending} onClick={() => target && revoke.mutate(target.agent_id, { onSuccess: () => { toast("Access revoked"); setTarget(null); }, onError: (e) => toast(errMsg(e), true) })}>{revoke.isPending ? "Revoking…" : "Revoke"}</button></>}>
        <p className="small muted" style={{ margin: 0 }}>{target && (index[target.agent_id]?.name ?? "This agent")} will no longer be able to call models through the gateway.</p>
      </Modal>
    </>
  );
}
