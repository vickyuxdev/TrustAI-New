"use client";
/** Shared governance dialogs. */
import { useState } from "react";
import { Modal, errMsg, useToast } from "@/components/ui";
import { useAgents, useRedteamLibrary, useStartEvaluation, type Evaluation } from "@/lib/governance";

/** Start a red-team run: pick agent (unless fixed), prompt count, benign share and attack categories. */
export function StartEvalModal({ open, onClose, agentId, onStarted }: { open: boolean; onClose: () => void; agentId?: string; onStarted?: (e: Evaluation) => void }) {
  const lib = useRedteamLibrary();
  const agents = useAgents({ limit: 200 });
  const start = useStartEvaluation();
  const toast = useToast();
  const [agent, setAgent] = useState(agentId ?? "");
  const [n, setN] = useState(40);
  const [benign, setBenign] = useState(30);
  const [threshold, setThreshold] = useState(95);
  const [cats, setCats] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const target = agentId ?? agent;
  const toggle = (id: string) => setCats((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));

  const submit = async () => {
    setErr(null);
    if (!target) return setErr("Choose the agent to red-team.");
    try {
      const e = await start.mutateAsync({ agentId: target, numGenerate: n, benignRatio: benign / 100, categories: cats, threshold });
      toast("Red-team run started");
      onClose();
      onStarted?.(e);
    } catch (e) { setErr(errMsg(e)); }
  };

  return (
    <Modal open={open} onClose={onClose} wide title="Start a red-team run" sub="Sends generated attack and benign prompts to the agent's endpoint and grades every response against its guardrails."
      footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button><button type="button" className="btn btn-primary" disabled={start.isPending} onClick={submit}>{start.isPending ? "Starting…" : `Run ${n} prompts`}</button></>}>
      {!agentId && (
        <div className="field"><label htmlFor="ev-agent">Agent</label>
          <select id="ev-agent" className="select-native" value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">Choose an agent…</option>
            {(agents.data?.items ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} · {a.external_id}</option>)}
          </select></div>
      )}
      <div className="field-row">
        <div className="field"><label htmlFor="ev-n">Prompts <b className="num" style={{ marginLeft: 6 }}>{n}</b></label><input id="ev-n" type="range" min={10} max={200} step={10} value={n} onChange={(e) => setN(+e.target.value)} /></div>
        <div className="field"><label htmlFor="ev-b">Benign share <b className="num" style={{ marginLeft: 6 }}>{benign}%</b></label><input id="ev-b" type="range" min={0} max={90} step={5} value={benign} onChange={(e) => setBenign(+e.target.value)} /></div>
        <div className="field"><label htmlFor="ev-t">Pass mark <b className="num" style={{ marginLeft: 6 }}>{threshold}</b></label><input id="ev-t" type="range" min={50} max={100} step={1} value={threshold} onChange={(e) => setThreshold(+e.target.value)} /></div>
      </div>
      <div className="field">
        <span className="lab">Attack categories <span className="muted" style={{ fontWeight: 400 }}>· none selected = all</span></span>
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          {(lib.data?.categories ?? []).map((c) => (
            <button key={c.id} type="button" className="btn btn-sm" aria-pressed={cats.includes(c.id)} onClick={() => toggle(c.id)}>
              {c.name}<span className="muted num" style={{ marginLeft: 4 }}>{c.seeds}</span>
            </button>
          ))}
          {lib.isLoading && <span className="small muted">Loading categories…</span>}
        </div>
      </div>
      <div className="banner"><span>Benign prompts measure over-blocking: a guardrail that refuses harmless questions lowers the trust score too.</span></div>
      {err && <div className="banner bad" role="alert">{err}</div>}
    </Modal>
  );
}
