"use client";
import { useMemo, useState } from "react";
import { Coins, Plus, Sparkles, Trash2 } from "lucide-react";
import { Card, CardHeader, Empty, ErrorState, Modal, PageHead, Pill, SkelRows, errMsg, useToast } from "@/components/ui";
import { useCreatePricing, useDeactivatePricing, usePricing, useSeedPricing } from "@/lib/api";
import { day, providerName } from "@/lib/format";

const price = (v: number | null) => (v == null ? "—" : `$${v.toFixed(v < 1 ? 3 : 2)}`);

export default function PricingPage() {
  const { data, isLoading, isError, error, refetch } = usePricing();
  const seed = useSeedPricing();
  const create = useCreatePricing();
  const off = useDeactivatePricing();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ provider: "azure_openai", model_name: "", input: "", output: "", cached: "", reasoning: "" });
  const [err, setErr] = useState<string | null>(null);
  const list = useMemo(() => (data ?? []).filter((p) => `${p.model_name} ${p.provider}`.toLowerCase().includes(q.toLowerCase())).sort((a, b) => a.provider.localeCompare(b.provider) || a.model_name.localeCompare(b.model_name)), [data, q]);

  const submit = async () => {
    setErr(null);
    const i = Number(f.input), o = Number(f.output);
    if (!f.model_name.trim()) return setErr("Enter the model name exactly as it appears in spans, e.g. gpt-4o.");
    if (Number.isNaN(i) || Number.isNaN(o) || f.input === "" || f.output === "") return setErr("Enter input and output prices per 1M tokens.");
    try {
      await create.mutateAsync({ provider: f.provider, model_name: f.model_name.trim(), input_price_per_1m: i, output_price_per_1m: o,
        cached_input_price_per_1m: f.cached ? Number(f.cached) : null, reasoning_price_per_1m: f.reasoning ? Number(f.reasoning) : null });
      toast("Price added"); setOpen(false);
    } catch (e) { setErr(errMsg(e)); }
  };

  return (
    <>
      <PageHead title="Model pricing" sub="Per-million-token prices the processor uses to cost every call. New prices apply to spans processed from now on."
        actions={<>
          <button type="button" className="btn" disabled={seed.isPending} onClick={() => seed.mutate(undefined, { onSuccess: (r) => toast(`Defaults loaded (${(r as { seeded?: number })?.seeded ?? 0} added)`), onError: (e) => toast(errMsg(e), true) })}><Sparkles className="ic" aria-hidden />Load defaults</button>
          <button type="button" className="btn btn-primary" onClick={() => { setErr(null); setOpen(true); }}><Plus className="ic" aria-hidden />Add price</button>
        </>} />
      <Card labelledBy="t-pr">
        <CardHeader id="t-pr" title="Active prices" sub={`${data?.length ?? 0} models`} action={<label className="search-in"><span className="sr">Search models</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search models or providers" /></label>} />
        <div style={{ marginTop: 12 }}>
          {isError ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading ? <SkelRows rows={6} /> : !list.length ? (
            <Empty icon={Coins} title={q ? "No models match" : "No prices yet"} action={!q && <button type="button" className="btn btn-primary" onClick={() => seed.mutate()}><Sparkles className="ic" aria-hidden />Load default prices</button>}>
              {q ? "Try another name." : "Without prices, calls are recorded but cost $0. Load the defaults or add your negotiated rates."}
            </Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead><tr><th>Model</th><th>Provider</th><th className="r">Input / 1M</th><th className="r">Output / 1M</th><th className="r">Cached input / 1M</th><th className="r">Reasoning / 1M</th><th>Status</th><th className="r">Effective from</th><th className="r"><span className="sr">Actions</span></th></tr></thead>
                <tbody>
                  {list.map((p) => (
                    <tr key={p.id}>
                      <td className="strong">{p.model_name}{p.model_version && <div className="sub">{p.model_version}</div>}</td>
                      <td className="muted">{providerName(p.provider)}</td>
                      <td className="r">{price(p.input_price_per_1m)}</td>
                      <td className="r">{price(p.output_price_per_1m)}</td>
                      <td className="r muted">{price(p.cached_input_price_per_1m)}</td>
                      <td className="r muted">{price(p.reasoning_price_per_1m)}</td>
                      <td><Pill tone={p.is_active ? "accent" : undefined} dot>{p.is_active ? "Active" : "Inactive"}</Pill></td>
                      <td className="r muted">{day(p.effective_from)}</td>
                      <td className="r">{p.is_active && <button type="button" className="icon-btn sm" aria-label={`Deactivate ${p.model_name}`} onClick={() => off.mutate(p.id, { onSuccess: () => toast("Price deactivated"), onError: (e) => toast(errMsg(e), true) })}><Trash2 className="ic" style={{ width: 14, height: 14 }} /></button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
      <Modal open={open} onClose={() => setOpen(false)} title="Add a model price" sub="USD per one million tokens."
        footer={<><button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button><button type="button" className="btn btn-primary" disabled={create.isPending} onClick={submit}>{create.isPending ? "Saving…" : "Add price"}</button></>}>
        <div className="field-row">
          <div className="field"><label htmlFor="mp-prov">Provider</label><select id="mp-prov" className="select-native" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })}>
            {["azure_openai", "azure_foundry", "openai", "anthropic", "aws_bedrock", "gcp_vertex"].map((p) => <option key={p} value={p}>{providerName(p)}</option>)}
          </select></div>
          <div className="field"><label htmlFor="mp-model">Model name</label><input id="mp-model" className="input" value={f.model_name} onChange={(e) => setF({ ...f, model_name: e.target.value })} placeholder="gpt-4o" /></div>
        </div>
        <div className="field-row">
          <div className="field"><label htmlFor="mp-in">Input price</label><input id="mp-in" className="input" inputMode="decimal" value={f.input} onChange={(e) => setF({ ...f, input: e.target.value })} placeholder="2.50" /></div>
          <div className="field"><label htmlFor="mp-out">Output price</label><input id="mp-out" className="input" inputMode="decimal" value={f.output} onChange={(e) => setF({ ...f, output: e.target.value })} placeholder="10.00" /></div>
        </div>
        <div className="field-row">
          <div className="field"><label htmlFor="mp-c">Cached input (optional)</label><input id="mp-c" className="input" inputMode="decimal" value={f.cached} onChange={(e) => setF({ ...f, cached: e.target.value })} placeholder="1.25" /></div>
          <div className="field"><label htmlFor="mp-r">Reasoning (optional)</label><input id="mp-r" className="input" inputMode="decimal" value={f.reasoning} onChange={(e) => setF({ ...f, reasoning: e.target.value })} /></div>
        </div>
        {err && <div className="banner bad" role="alert">{err}</div>}
      </Modal>
    </>
  );
}
