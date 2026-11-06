"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Building2, Pencil, Plus, Search, Wallet, Zap } from "lucide-react";
import { BreakdownRow } from "@/components/blocks";
import { SERIES } from "@/components/charts";
import { Card, CardHeader, Drawer, Empty, ErrorState, Kpi, Modal, PageHead, Pill, Seg, ShareCell, SkelRows, errMsg, useToast } from "@/components/ui";
import { useClients, useCreateClient, useProjects, useUpdateClient, type Client, type ClientType } from "@/lib/api";
import { compact, day, share, usd } from "@/lib/format";

const slugify = (s: string) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 100);
const TYPE_LABEL: Record<ClientType, string> = { external: "External customer", internal: "Internal team" };

function Budget({ spent, budget }: { spent: number; budget: number | null }) {
  if (!budget) return <span className="muted">No budget</span>;
  const f = spent / budget;
  const color = f > 1 ? "var(--danger)" : f > 0.8 ? "var(--wait)" : "var(--accent)";
  return (
    <span className="meter" style={{ minWidth: 150 }} title={`${usd(spent)} of ${usd(budget)}`}>
      <span className="bar-track" aria-hidden><i style={{ width: `${Math.min(100, f * 100)}%`, background: color }} /></span>
      <b className="num small" style={{ color: f > 1 ? "var(--danger)" : "var(--text-2)", minWidth: 40, textAlign: "right" }}>{Math.round(f * 100)}%</b>
    </span>
  );
}

export default function ClientsPage() {
  const { data, isLoading, isError, error, refetch } = useClients(30);
  const projects = useProjects(30);
  const [q, setQ] = useState("");
  const [type, setType] = useState<"all" | ClientType>("all");
  const [sel, setSel] = useState<Client | null>(null);
  const [form, setForm] = useState<{ open: boolean; client?: Client }>({ open: false });
  const items = useMemo(() => data?.items ?? [], [data]);
  const list = items
    .filter((c) => (type === "all" || c.client_type === type) && `${c.name} ${c.slug} ${c.description ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0));
  const spend = items.reduce((a, c) => a + (c.total_cost_usd ?? 0), 0);
  const calls = items.reduce((a, c) => a + (c.total_calls ?? 0), 0);
  const over = items.filter((c) => c.monthly_budget_usd && (c.total_cost_usd ?? 0) > c.monthly_budget_usd);
  const ext = items.filter((c) => c.client_type === "external").length;
  const ranked = [...items].sort((a, b) => (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0));
  const color = (id: string) => { const i = ranked.findIndex((c) => c.id === id); return i < 4 ? SERIES[i] : "var(--c5)"; };
  const slices = (() => {
    const head = ranked.filter((c) => (c.total_cost_usd ?? 0) > 0).slice(0, 4).map((c, i) => ({ name: c.name, value: c.total_cost_usd ?? 0, color: SERIES[i] }));
    const rest = ranked.slice(4).reduce((a, c) => a + (c.total_cost_usd ?? 0), 0);
    return rest > 0 ? [...head, { name: "Other", value: rest, color: "var(--c5)" }] : head;
  })();
  const byType = (["external", "internal"] as const).map((t, i) => ({ name: TYPE_LABEL[t], value: items.filter((c) => c.client_type === t).reduce((a, c) => a + (c.total_cost_usd ?? 0), 0), color: i ? "var(--s3)" : "var(--s1)" })).filter((s) => s.value > 0);

  return (
    <>
      <PageHead title="Clients" sub="The customers and internal teams your AI projects belong to. Spend and calls cover the last 30 days."
        actions={<button type="button" className="btn btn-primary" onClick={() => setForm({ open: true })}><Plus className="ic" aria-hidden />New client</button>} />

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Client figures">
        <Kpi icon={Building2} label="Active clients" value={isLoading ? "—" : compact(data?.total)} foot={`${ext} external · ${items.length - ext} internal`} />
        <Kpi icon={Wallet} label="Spend · 30 days" value={isLoading ? "—" : usd(spend)} foot={ranked[0] && spend ? `${ranked[0].name} is ${share((ranked[0].total_cost_usd ?? 0) / spend)}` : "No spend yet"} />
        <Kpi icon={Zap} label="AI calls · 30 days" value={isLoading ? "—" : compact(calls)} foot={calls ? `${usd(spend / calls)} per call on average` : "No calls yet"} />
        <Kpi icon={Wallet} label="Over budget" tone={over.length ? "bad" : undefined} value={isLoading ? "—" : String(over.length)} foot={`${items.filter((c) => c.monthly_budget_usd).length} of ${items.length} clients have a monthly budget`} />
      </section>

      <div className="split-wide" style={{ alignItems: "start" }}>
        <Card labelledBy="t-cl">
          <CardHeader id="t-cl" title="All clients" sub="Click a client to see its projects"
            action={<div className="filterbar">
              <label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Search clients</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search clients" /></label>
              <Seg small label="Client type" value={type} onChange={setType} options={[["all", "All"], ["external", "External"], ["internal", "Internal"]] as const} />
            </div>} />
          <div style={{ marginTop: 12 }}>
            {isError ? <div className="card-b"><ErrorState error={error} onRetry={() => refetch()} /></div> : isLoading ? <SkelRows rows={6} /> : !list.length ? (
              <Empty icon={Building2} title={q || type !== "all" ? "No clients match" : "No clients yet"}
                action={!q && type === "all" && <button type="button" className="btn btn-primary" onClick={() => setForm({ open: true })}><Plus className="ic" aria-hidden />Add your first client</button>}>
                {q || type !== "all" ? "Try another name or type." : "Add a client to group its projects and track its AI spend against a budget."}
              </Empty>
            ) : (
              <div className="scroll-x"><table>
                <thead><tr><th>Client</th><th className="r">Projects</th><th className="r">Spend</th><th>Share of spend</th><th className="r">AI calls</th><th>Monthly budget</th></tr></thead>
                <tbody>{list.map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => setSel(c)}>
                    <td><div className="cell-main"><span className="ico" aria-hidden><Building2 className="ic" /></span><div><b>{c.name}</b><small>{TYPE_LABEL[c.client_type]}</small></div></div></td>
                    <td className="r">{c.active_projects ?? 0}</td>
                    <td className="r strong">{usd(c.total_cost_usd ?? 0)}</td>
                    <td><ShareCell fraction={spend ? (c.total_cost_usd ?? 0) / spend : 0} color={color(c.id)} label={share(spend ? (c.total_cost_usd ?? 0) / spend : 0)} /></td>
                    <td className="r">{compact(c.total_calls ?? 0)}</td>
                    <td><Budget spent={c.total_cost_usd ?? 0} budget={c.monthly_budget_usd} /></td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </div>
        </Card>

        <Card labelledBy="t-mix">
          <CardHeader id="t-mix" title="Where spend goes" sub={`Share of ${usd(spend)} · last 30 days`} />
          {isLoading ? <SkelRows rows={5} /> : (
            <div className="bk">
              <BreakdownRow title="By client" slices={slices} />
              <BreakdownRow title="By client type" slices={byType} />
            </div>
          )}
        </Card>
      </div>

      <Drawer open={!!sel} onClose={() => setSel(null)} title={sel?.name ?? ""} sub={sel ? `${TYPE_LABEL[sel.client_type]} · since ${day(sel.created_at)}` : undefined}
        actions={sel && <button type="button" className="btn btn-sm" onClick={() => setForm({ open: true, client: sel })}><Pencil className="ic" aria-hidden />Edit</button>}>
        {sel && (
          <div className="stack">
            {sel.description && <p className="small muted" style={{ margin: 0 }}>{sel.description}</p>}
            <dl className="kv">
              <dt>Spend · 30 days</dt><dd>{usd(sel.total_cost_usd ?? 0)}</dd>
              <dt>AI calls · 30 days</dt><dd>{compact(sel.total_calls ?? 0)}</dd>
              <dt>Monthly budget</dt><dd>{sel.monthly_budget_usd ? usd(sel.monthly_budget_usd) : "Not set"}</dd>
              <dt>Budget used</dt><dd><Budget spent={sel.total_cost_usd ?? 0} budget={sel.monthly_budget_usd} /></dd>
              <dt>Slug</dt><dd>{sel.slug}</dd>
            </dl>
            <section>
              <h3 className="card-t" style={{ marginBottom: 4 }}>Projects</h3>
              {projects.isLoading ? <SkelRows rows={3} /> : (() => {
                const ps = (projects.data?.items ?? []).filter((p) => p.client_id === sel.id).sort((a, b) => (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0));
                return !ps.length ? <p className="small muted">No projects for this client yet.</p> : (
                  <ul className="list">{ps.map((p) => (
                    <li key={p.id}>
                      <div style={{ minWidth: 0 }}><Link href={`/projects/${p.id}`} className="strong">{p.name}</Link><div className="small muted">{compact(p.total_calls ?? 0)} calls</div></div>
                      <b className="num">{usd(p.total_cost_usd ?? 0)}</b>
                    </li>))}</ul>
                );
              })()}
            </section>
            {!sel.is_active && <Pill tone="danger" dot>Inactive</Pill>}
          </div>
        )}
      </Drawer>

      <ClientForm open={form.open} client={form.client} onClose={() => setForm({ open: false })} onSaved={(c) => { if (sel?.id === c.id) setSel({ ...sel, ...c }); }} />
    </>
  );
}

function ClientForm({ open, onClose, client, onSaved }: { open: boolean; onClose: () => void; client?: Client; onSaved?: (c: Client) => void }) {
  const create = useCreateClient();
  const update = useUpdateClient(client?.id ?? "");
  const toast = useToast();
  const [f, setF] = useState({ name: "", slug: "", type: "external" as ClientType, desc: "", budget: "" });
  const [slugTouched, setSlugTouched] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const sig = open ? (client?.id ?? "new") : null;
  const [prev, setPrev] = useState<string | null>(null);
  if (sig !== prev) {
    setPrev(sig);
    if (sig) {
      setF({ name: client?.name ?? "", slug: client?.slug ?? "", type: client?.client_type ?? "external", desc: client?.description ?? "", budget: client?.monthly_budget_usd != null ? String(client.monthly_budget_usd) : "" });
      setSlugTouched(!!client); setErr(null);
    }
  }
  const busy = create.isPending || update.isPending;
  const submit = async () => {
    setErr(null);
    if (f.name.trim().length < 2) return setErr("Give the client a name of at least 2 characters.");
    if (!client && !/^[a-z0-9-]{2,100}$/.test(f.slug)) return setErr("The slug can use lowercase letters, numbers and dashes (2+ characters).");
    const b = f.budget.trim() ? Number(f.budget) : null;
    if (b != null && (Number.isNaN(b) || b < 0)) return setErr("The monthly budget must be a positive number.");
    try {
      const saved = client
        ? await update.mutateAsync({ name: f.name.trim(), description: f.desc.trim() || null, monthly_budget_usd: b })
        : await create.mutateAsync({ name: f.name.trim(), slug: f.slug, client_type: f.type, description: f.desc.trim() || null, monthly_budget_usd: b });
      toast(client ? "Client saved" : `Client “${saved.name}” added`);
      onSaved?.(saved);
      onClose();
    } catch (e) { setErr(errMsg(e)); }
  };
  return (
    <Modal open={open} onClose={onClose} title={client ? "Edit client" : "New client"} sub={client ? client.slug : "A customer or internal team that owns AI projects."}
      footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button><button type="button" className="btn btn-primary" disabled={busy} onClick={submit}>{busy ? "Saving…" : client ? "Save changes" : "Add client"}</button></>}>
      <div className="field"><label htmlFor="cf-name">Name</label>
        <input id="cf-name" className="input" value={f.name} placeholder="Acme Insurance" onChange={(e) => setF((x) => ({ ...x, name: e.target.value, slug: !slugTouched && !client ? slugify(e.target.value) : x.slug }))} /></div>
      {!client && (
        <div className="field-row">
          <div className="field"><label htmlFor="cf-slug">Slug</label><input id="cf-slug" className="input" value={f.slug} onChange={(e) => { setSlugTouched(true); setF((x) => ({ ...x, slug: e.target.value })); }} placeholder="acme-insurance" /></div>
          <div className="field"><label htmlFor="cf-type">Type</label>
            <select id="cf-type" className="select-native" value={f.type} onChange={(e) => setF((x) => ({ ...x, type: e.target.value as ClientType }))}>
              <option value="external">External customer</option><option value="internal">Internal team</option>
            </select></div>
        </div>
      )}
      <div className="field"><label htmlFor="cf-desc">Description</label><textarea id="cf-desc" className="textarea" rows={2} value={f.desc} onChange={(e) => setF((x) => ({ ...x, desc: e.target.value }))} placeholder="Optional" /></div>
      <div className="field"><label htmlFor="cf-b">Monthly budget (USD)</label><input id="cf-b" className="input" inputMode="decimal" value={f.budget} onChange={(e) => setF((x) => ({ ...x, budget: e.target.value }))} placeholder="Optional, e.g. 5000" /></div>
      {err && <div className="banner bad" role="alert">{err}</div>}
    </Modal>
  );
}
