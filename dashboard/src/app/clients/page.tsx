"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Building2, ChevronRight, Pencil, Plus, Search, Wallet, Zap } from "lucide-react";
import { MiniBars, Ring, SERIES, Segments, Sparkline, StackedBars } from "@/components/charts";
import { Card, CardHeader, Delta, Drawer, Empty, ErrorState, Kpi, Modal, PageHead, Pill, Seg, Skel, SkelRows, errMsg, useToast } from "@/components/ui";
import { useClients, useCostBreakdown, useCostBreakdowns, useCreateClient, useOverviewMetrics, useProjects, useUpdateClient, type Client, type ClientType } from "@/lib/api";
import { compact, day, share, usd, usdShort } from "@/lib/format";
import { fillDays } from "@/lib/series";
import { resolveTimeRange, timeRangeKey, type TimeRangeSpec } from "@/lib/timeRange";

const slugify = (s: string) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 100);
const TYPE_LABEL: Record<ClientType, string> = { external: "External customer", internal: "Internal team" };
const SPEC30: TimeRangeSpec = { kind: "preset", preset: "30d" };
const KEY30 = timeRangeKey(SPEC30);
type Tone = "over" | "near" | "ok" | "none";
const TONE: Record<Tone, { label: string; color: string; cls: string }> = {
  over: { label: "Over budget", color: "var(--danger)", cls: "bad" }, near: { label: "Near limit", color: "var(--wait)", cls: "wait" },
  ok: { label: "On track", color: "var(--accent)", cls: "ok" }, none: { label: "No budget", color: "var(--line-2)", cls: "idle" },
};
const budgetTone = (c: Client): Tone => !c.monthly_budget_usd ? "none" : (c.total_cost_usd ?? 0) > c.monthly_budget_usd ? "over" : (c.total_cost_usd ?? 0) >= 0.8 * c.monthly_budget_usd ? "near" : "ok";
const initials = (n: string) => n.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

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
  const ov = useOverviewMetrics(SPEC30, KEY30);
  const all = useCostBreakdown(SPEC30, KEY30);
  const [q, setQ] = useState("");
  const [type, setType] = useState<"all" | ClientType>("all");
  const [sel, setSel] = useState<Client | null>(null);
  const [form, setForm] = useState<{ open: boolean; client?: Client }>({ open: false });
  const items = useMemo(() => data?.items ?? [], [data]);
  const ranked = useMemo(() => [...items].sort((a, b) => (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0)), [items]);
  const perClient = useCostBreakdowns(SPEC30, KEY30, ranked.map((c) => ({ client_id: c.id })));
  const range = useMemo(() => resolveTimeRange(SPEC30), []);
  const days = useMemo(() => fillDays(all.data?.time_series ?? [], range.from, range.to), [all.data, range]);
  const clientDays = ranked.map((_, i) => fillDays(perClient[i]?.data?.time_series ?? [], range.from, range.to));
  const colorOf = (id: string) => SERIES[ranked.findIndex((c) => c.id === id) % SERIES.length] ?? "var(--c5)";

  const spend = items.reduce((a, c) => a + (c.total_cost_usd ?? 0), 0);
  const calls = items.reduce((a, c) => a + (c.total_calls ?? 0), 0);
  const ext = items.filter((c) => c.client_type === "external");
  const counts: Record<Tone, number> = { over: 0, near: 0, ok: 0, none: 0 };
  items.forEach((c) => counts[budgetTone(c)]++);
  const projectsOf = (id: string) => (projects.data?.items ?? []).filter((p) => p.client_id === id);
  const list = ranked.filter((c) => (type === "all" || c.client_type === type) && `${c.name} ${c.slug} ${c.description ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  const extSpend = ext.reduce((a, c) => a + (c.total_cost_usd ?? 0), 0);

  return (
    <>
      <PageHead title="Clients" sub="The customers and internal teams your AI projects belong to. Figures cover the last 30 days."
        actions={<button type="button" className="btn btn-primary" onClick={() => setForm({ open: true })}><Plus className="ic" aria-hidden />New client</button>} />

      <section className="kpis" data-cols={4} style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Client figures">
        <Kpi icon={Building2} label="Active clients" value={isLoading ? <Skel w={40} h={22} /> : compact(items.length)}
          vis={items.length ? <Ring size={34} stroke={5} ariaLabel="External vs internal clients" slices={[{ name: "External", value: ext.length, color: "var(--s1)" }, { name: "Internal", value: items.length - ext.length, color: "var(--s3)" }]} /> : undefined}
          foot={`${ext.length} external · ${items.length - ext.length} internal · ${projects.data?.items.length ?? 0} projects`} />
        <Kpi icon={Wallet} label="Spend · 30 days" value={isLoading ? <Skel w={110} h={22} /> : usd(spend)}
          vis={<Sparkline values={days.map((d) => d.cost)} width={88} height={30} />}
          foot={ov.data ? <><Delta pct={ov.data.cost_trend_pct} />vs previous 30 days</> : "—"} />
        <Kpi icon={Zap} label="AI calls · 30 days" value={isLoading ? <Skel w={80} h={22} /> : compact(calls)}
          vis={<MiniBars values={days.slice(-12).map((d) => d.calls)} width={72} height={30} />}
          foot={<>{ov.data && <Delta pct={ov.data.calls_trend_pct} />}{calls ? `${usd(spend / calls)} per call` : "No calls"}</>} />
        <Kpi icon={Wallet} label="Budget health" tone={counts.over ? "bad" : undefined}
          value={isLoading ? <Skel w={90} h={22} /> : counts.over ? <span style={{ color: "var(--danger)" }}>{counts.over} over</span> : "On track"}
          vis={<div style={{ width: 88 }}><Segments ariaLabel="Clients by budget use" parts={(Object.keys(TONE) as Tone[]).map((t) => ({ value: counts[t], color: TONE[t].color, label: TONE[t].label }))} /></div>}
          foot={`${counts.near} near limit · ${counts.ok} on track · ${counts.none} no budget`} />
      </section>

      <Card labelledBy="t-cl">
        <CardHeader id="t-cl" title="All clients" sub={`${list.length} of ${items.length} · click a client to see its projects`}
          action={<div className="filterbar">
            <Seg small label="Client type" value={type} onChange={setType} options={[["all", `All ${items.length}`], ["external", `External ${ext.length}`], ["internal", `Internal ${items.length - ext.length}`]] as const} />
            <label className="search-in"><Search className="ic" aria-hidden /><span className="sr">Search clients</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search clients" /></label>
          </div>} />
        <div style={{ marginTop: 12 }}>
          {isError ? <div className="card-b"><ErrorState error={error} onRetry={() => refetch()} /></div> : isLoading ? <SkelRows rows={5} /> : !list.length ? (
            <Empty icon={Building2} title={q || type !== "all" ? "No clients match" : "No clients yet"}
              action={!q && type === "all" && <button type="button" className="btn btn-primary" onClick={() => setForm({ open: true })}><Plus className="ic" aria-hidden />Add your first client</button>}>
              {q || type !== "all" ? "Try another name or type." : "Add a client to group its projects and track its AI spend against a budget."}
            </Empty>
          ) : (
            <div className="scroll-x">
              <table className="cl-table">
                <thead><tr><th>Client</th><th>Projects</th><th>Spend · 30 days</th><th>Trend</th><th className="r">AI calls</th><th>Monthly budget</th><th className="r">Client since</th><th aria-label="Open" /></tr></thead>
                <tbody>
                  {list.map((c) => {
                    const i = ranked.findIndex((x) => x.id === c.id);
                    const ps = projectsOf(c.id);
                    const t = budgetTone(c);
                    const cs = c.total_cost_usd ?? 0;
                    return (
                      <tr key={c.id} className="clickable" onClick={() => setSel(c)}>
                        <td>
                          <div className="cell-main">
                            <span className="cl-mono" aria-hidden>{initials(c.name)}</span>
                            <div style={{ minWidth: 0 }}><b>{c.name}</b><small className="cl-desc">{TYPE_LABEL[c.client_type]}{c.description ? ` · ${c.description}` : ""}</small></div>
                          </div>
                        </td>
                        <td><b className="num">{ps.length || c.active_projects || 0}</b><div className="sub cl-proj" title={ps.map((p) => p.name).join(", ")}>{ps.map((p) => p.name).join(", ") || "—"}</div></td>
                        <td>
                          <div className="ag-metric" style={{ minWidth: 170, maxWidth: 220 }}>
                            <span className="ag-v"><b className="num">{usd(cs)}</b><small>{share(spend ? cs / spend : 0)} of spend</small></span>
                            <span className="ag-bar"><i style={{ width: `${(cs / (ranked[0]?.total_cost_usd || 1)) * 100}%`, background: colorOf(c.id) }} /></span>
                          </div>
                        </td>
                        <td>{perClient[i]?.isLoading ? <Skel w={96} h={24} /> : <Sparkline values={clientDays[i].map((d) => d.cost)} width={96} height={26} color={colorOf(c.id)} />}</td>
                        <td className="r"><b className="num">{compact(c.total_calls ?? 0)}</b><div className="sub">{c.total_calls ? `${usd(cs / c.total_calls)} / call` : "—"}</div></td>
                        <td>
                          {c.monthly_budget_usd ? (
                            <div className="ag-metric" style={{ minWidth: 190, maxWidth: 240 }}>
                              <span className="ag-v"><b className="num" style={{ color: t === "over" ? "var(--danger)" : undefined }}>{Math.round((cs / c.monthly_budget_usd) * 100)}%<small style={{ marginLeft: 6 }}>of {usdShort(c.monthly_budget_usd)}</small></b><span className={`ag-health ${TONE[t].cls}`}><i aria-hidden />{TONE[t].label}</span></span>
                              <span className="ag-bar"><i style={{ width: `${Math.min(1, cs / c.monthly_budget_usd) * 100}%`, background: TONE[t].color }} /></span>
                            </div>
                          ) : <span className="ag-health idle"><i aria-hidden />No budget</span>}
                        </td>
                        <td className="r muted">{day(c.created_at)}</td>
                        <td className="r"><ChevronRight className="ic cl-go" aria-hidden /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      <Card labelledBy="t-mix">
        <CardHeader id="t-mix" title="Where spend goes" sub={`Daily spend by client · ${usd(spend)} over the last 30 days`} />
        <div className="cl-mix">
          <div className="cl-chart">
            {all.isLoading || perClient.some((r) => r.isLoading) ? <Skel h={240} /> : (
              <StackedBars height={240} ariaLabel="Daily spend by client" labels={days.map((d) => d.label)} longs={days.map((d) => d.long)}
                series={ranked.map((c, i) => ({ name: c.name, color: colorOf(c.id), values: clientDays[i].map((d) => d.cost) }))} fmt={(v) => usd(v)} fmtAxis={usdShort} />
            )}
          </div>
          <div className="cl-side">
            <section>
              <h3>By client</h3>
              <ul className="cl-rank">
                {ranked.map((c) => (
                  <li key={c.id}>
                    <i style={{ background: colorOf(c.id) }} aria-hidden />
                    <span className="n">{c.name}</span>
                    <span className="bar-track" aria-hidden><i style={{ width: `${spend ? ((c.total_cost_usd ?? 0) / spend) * 100 : 0}%`, background: colorOf(c.id) }} /></span>
                    <b className="num">{share(spend ? (c.total_cost_usd ?? 0) / spend : 0)}</b>
                    <span className="v num">{usd(c.total_cost_usd ?? 0)}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h3>By client type</h3>
              <Segments ariaLabel="Spend by client type" parts={[{ value: extSpend, color: "var(--s1)", label: "External" }, { value: spend - extSpend, color: "var(--s3)", label: "Internal" }]} />
              <ul className="seg-legend" style={{ marginTop: 8 }}>
                <li><i style={{ background: "var(--s1)" }} />External customers <b>{share(spend ? extSpend / spend : 0)}</b>&nbsp;· {usd(extSpend)}</li>
                <li><i style={{ background: "var(--s3)" }} />Internal teams <b>{share(spend ? (spend - extSpend) / spend : 0)}</b>&nbsp;· {usd(spend - extSpend)}</li>
              </ul>
            </section>
          </div>
        </div>
      </Card>

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
                const ps = projectsOf(sel.id).sort((a, b) => (b.total_cost_usd ?? 0) - (a.total_cost_usd ?? 0));
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
