"use client";
import { useMemo, useState } from "react";
import { Bell, BellRing, CircleCheck, Plus, Trash2 } from "lucide-react";
import { Card, CardHeader, Empty, ErrorState, Kpi, Modal, PageHead, Pill, SkelRows, Tabs, errMsg, useToast } from "@/components/ui";
import { useAlertAction, useAlertRules, useAlerts, useCreateAlertRule, useDeleteAlertRule, useProjects, type AlertRule, type Severity } from "@/lib/api";
import { ago, day, when } from "@/lib/format";
import { projectLabels } from "@/lib/projects";

const METRICS = [
  { value: "cost_usd", label: "Spend (USD)", unit: "$" },
  { value: "error_rate", label: "Error rate (%)", unit: "%" },
  { value: "latency_p99", label: "Latency p99 (ms)", unit: "ms" },
];
const OPS: Record<AlertRule["operator"], string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=" };
const SEV_TONE: Record<Severity, "danger" | "wait" | undefined> = { critical: "danger", warning: "wait", info: undefined };
type StatusTab = "active" | "acknowledged" | "resolved" | "all";

function metricLabel(m: string) { return METRICS.find((x) => x.value === m)?.label ?? m; }
function fmtThreshold(r: AlertRule) {
  const u = METRICS.find((x) => x.value === r.metric)?.unit;
  return u === "$" ? `$${r.threshold}` : u ? `${r.threshold}${u === "%" ? "%" : " " + u}` : String(r.threshold);
}

export default function AlertsPage() {
  const [tab, setTab] = useState<StatusTab>("active");
  const alerts = useAlerts(tab);
  const active = useAlerts("active");
  const rules = useAlertRules();
  const projects = useProjects();
  const act = useAlertAction();
  const del = useDeleteAlertRule();
  const create = useCreateAlertRule();
  const toast = useToast();
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const ruleById = useMemo(() => Object.fromEntries((rules.data?.items ?? []).map((r) => [r.id, r])), [rules.data]);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", metric: "cost_usd", operator: "gt" as AlertRule["operator"], threshold: "", window: "60", severity: "warning" as Severity, project: "", channels: "" });
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    const th = Number(form.threshold);
    if (!form.name.trim()) return setErr("Give the rule a name.");
    if (form.threshold === "" || Number.isNaN(th)) return setErr("Enter a numeric threshold.");
    try {
      await create.mutateAsync({ name: form.name.trim(), metric: form.metric, operator: form.operator, threshold: th, window_minutes: Number(form.window) || 60, severity: form.severity,
        notification_channels: form.channels.split(",").map((c) => c.trim()).filter(Boolean), project_id: form.project || null });
      toast("Alert rule created"); setOpen(false);
    } catch (e) { setErr(errMsg(e)); }
  };

  const ruleList = rules.data?.items ?? [];
  const crit = (active.data?.items ?? []).filter((a) => ruleById[a.rule_id]?.severity === "critical").length;

  return (
    <>
      <PageHead title="Alerts" sub="Fired alerts and the rules that watch spend, error rate and latency."
        actions={<button type="button" className="btn btn-primary" onClick={() => { setForm({ name: "", metric: "cost_usd", operator: "gt", threshold: "", window: "60", severity: "warning", project: "", channels: "" }); setErr(null); setOpen(true); }}><Plus className="ic" aria-hidden />New rule</button>} />

      <section className="kpis" style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Alert figures">
        <Kpi icon={BellRing} label="Active alerts" tone={active.data?.total ? "bad" : undefined} value={active.isLoading ? "—" : String(active.data?.total ?? 0)} foot={active.data?.total ? "Waiting for someone to acknowledge" : "Nothing needs attention"} />
        <Kpi icon={BellRing} label="Critical" tone={crit ? "bad" : undefined} value={active.isLoading ? "—" : String(crit)} foot="Active alerts from critical rules" />
        <Kpi icon={Bell} label="Alert rules" value={rules.isLoading ? "—" : String(ruleList.length)} foot={`${ruleList.filter((r) => r.is_active).length} enabled`} />
        <Kpi icon={CircleCheck} label="Last fired" value={active.data?.items[0] ? ago(active.data.items[0].triggered_at) : "—"} foot={active.data?.items[0]?.message ?? "No active alerts"} />
      </section>

      <div className="split-wide">
        <Card labelledBy="t-al">
          <CardHeader id="t-al" title="Fired alerts" sub="Acknowledge to show you're on it; resolve when it's fixed." />
          <div style={{ padding: "6px 18px 0" }}>
            <Tabs label="Alert status" value={tab} onChange={setTab} tabs={[{ id: "active", label: "Active", count: active.data?.total ?? null }, { id: "acknowledged", label: "Acknowledged" }, { id: "resolved", label: "Resolved" }, { id: "all", label: "All" }]} />
          </div>
          {alerts.isError ? <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} /> : alerts.isLoading ? <SkelRows rows={5} /> : !alerts.data?.items.length ? (
            <Empty icon={CircleCheck} title={tab === "active" ? "No active alerts" : "Nothing here"}>{tab === "active" ? "All rules are within their thresholds." : "No alerts with this status."}</Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead><tr><th>Alert</th><th>Severity</th><th className="r">Value</th><th>Status</th><th className="r">Triggered</th><th className="r"><span className="sr">Actions</span></th></tr></thead>
                <tbody>
                  {alerts.data.items.map((a) => {
                    const r = ruleById[a.rule_id];
                    return (
                      <tr key={a.id}>
                        <td><div className="cell-main"><span className="ico" style={{ background: "var(--danger-soft)", color: "var(--danger)" }} aria-hidden><BellRing className="ic" /></span><div><b>{a.message}</b><small>{r ? `${r.name} · ${metricLabel(r.metric)} ${OPS[r.operator]} ${fmtThreshold(r)}` : "Rule deleted"}</small></div></div></td>
                        <td>{r ? <Pill tone={SEV_TONE[r.severity]} dot>{r.severity}</Pill> : "—"}</td>
                        <td className="r strong">{a.triggered_value.toLocaleString("en-US", { maximumFractionDigits: 4 })}</td>
                        <td><Pill tone={a.status === "active" ? "danger" : a.status === "acknowledged" ? "wait" : "accent"} dot>{a.status}</Pill></td>
                        <td className="r muted nowrap" title={when(a.triggered_at)}>{ago(a.triggered_at)}</td>
                        <td className="r nowrap">
                          {a.status === "active" && <button type="button" className="btn btn-sm" disabled={act.isPending} onClick={() => act.mutate({ id: a.id, action: "acknowledge" }, { onSuccess: () => toast("Alert acknowledged"), onError: (e) => toast(errMsg(e), true) })}>Acknowledge</button>}{" "}
                          {a.status !== "resolved" && <button type="button" className="btn btn-sm" disabled={act.isPending} onClick={() => act.mutate({ id: a.id, action: "resolve" }, { onSuccess: () => toast("Alert resolved"), onError: (e) => toast(errMsg(e), true) })}>Resolve</button>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card labelledBy="t-rules">
          <CardHeader id="t-rules" title="Rules" sub={`${ruleList.length} rules`} bordered />
          {rules.isError ? <ErrorState error={rules.error} onRetry={() => rules.refetch()} /> : rules.isLoading ? <SkelRows rows={4} /> : !ruleList.length ? (
            <Empty icon={Bell} title="No rules yet" action={<button type="button" className="btn btn-sm" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />New rule</button>}>Watch spend, error rate or p99 latency and get alerted when a threshold is crossed.</Empty>
          ) : (
            <ul className="list" style={{ padding: "0 18px" }}>
              {ruleList.map((r) => (
                <li key={r.id}>
                  <div style={{ minWidth: 0 }}>
                    <div className="row"><b className="ellipsis">{r.name}</b><Pill tone={SEV_TONE[r.severity]}>{r.severity}</Pill></div>
                    <div className="small muted">{metricLabel(r.metric)} {OPS[r.operator]} {fmtThreshold(r)} · over {r.window_minutes} min{r.notification_channels.length ? ` · ${r.notification_channels.join(", ")}` : ""} · added {day(r.created_at)}</div>
                  </div>
                  <button type="button" className="icon-btn sm" aria-label={`Delete rule ${r.name}`} onClick={() => del.mutate(r.id, { onSuccess: () => toast("Rule deleted"), onError: (e) => toast(errMsg(e), true) })}><Trash2 className="ic" style={{ width: 14, height: 14 }} /></button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="New alert rule" sub="Fires when the metric crosses the threshold over the window."
        footer={<><button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button><button type="button" className="btn btn-primary" disabled={create.isPending} onClick={submit}>{create.isPending ? "Creating…" : "Create rule"}</button></>}>
        <div className="field"><label htmlFor="ar-name">Name</label><input id="ar-name" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Daily spend over $50" /></div>
        <div className="field-row">
          <div className="field"><label htmlFor="ar-metric">Metric</label><select id="ar-metric" className="select-native" value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })}>{METRICS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}</select></div>
          <div className="field"><label htmlFor="ar-project">Project</label><select id="ar-project" className="select-native" value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })}><option value="">All projects</option>{(projects.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{labels[p.id]}</option>)}</select></div>
        </div>
        <div className="field-row">
          <div className="field"><label htmlFor="ar-op">Condition</label><select id="ar-op" className="select-native" value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value as AlertRule["operator"] })}><option value="gt">Greater than</option><option value="gte">At least</option><option value="lt">Less than</option><option value="lte">At most</option><option value="eq">Equal to</option></select></div>
          <div className="field"><label htmlFor="ar-th">Threshold</label><input id="ar-th" className="input" inputMode="decimal" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value })} placeholder="50" /></div>
        </div>
        <div className="field-row">
          <div className="field"><label htmlFor="ar-win">Window (minutes)</label><input id="ar-win" className="input" inputMode="numeric" value={form.window} onChange={(e) => setForm({ ...form, window: e.target.value })} /></div>
          <div className="field"><label htmlFor="ar-sev">Severity</label><select id="ar-sev" className="select-native" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value as Severity })}><option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option></select></div>
        </div>
        <div className="field"><label htmlFor="ar-ch">Notification channels</label><input id="ar-ch" className="input" value={form.channels} onChange={(e) => setForm({ ...form, channels: e.target.value })} placeholder="email:ops@company.com, slack:#ai-alerts" /><span className="hint">Optional. Separate several with commas.</span></div>
        {err && <div className="banner bad" role="alert">{err}</div>}
      </Modal>
    </>
  );
}
