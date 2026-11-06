"use client";
import { useMemo, useState } from "react";
import { Cloud, CircleCheck, Pencil, Plug, Plus, RefreshCw, TriangleAlert, Trash2, Zap } from "lucide-react";
import { Card, CardHeader, Empty, ErrorState, Kpi, Modal, PageHead, Pill, SkelRows, errMsg, useToast } from "@/components/ui";
import {
  useConnectors, useCreateConnector, useDeleteConnector, useProjects, useSyncConnector, useTestConnector, useUpdateConnector,
  type Connector, type ConnectorProvider,
} from "@/lib/api";
import { ago, compact, providerName } from "@/lib/format";
import { projectLabels } from "@/lib/projects";

type FieldDef = { key: string; label: string; placeholder?: string; in: "config" | "credentials"; secret?: boolean; hint?: string; required?: boolean };
const PROVIDERS: { id: ConnectorProvider; blurb: string; soon?: boolean; fields: FieldDef[]; auth?: string }[] = [
  { id: "azure_openai", blurb: "Usage and cost metrics from Azure OpenAI deployments.", auth: "Use an API key, or a service principal (tenant, client ID, secret).", fields: [
    { key: "endpoint", label: "Endpoint URL", placeholder: "https://<resource>.openai.azure.com", in: "config", required: true },
    { key: "api_version", label: "API version", placeholder: "2024-02-01", in: "config" },
    { key: "resource_id", label: "Azure resource ID", placeholder: "/subscriptions/…/providers/Microsoft.CognitiveServices/accounts/…", in: "config", hint: "Needed for Azure Monitor metrics." },
    { key: "api_key", label: "API key", in: "credentials", secret: true },
    { key: "tenant_id", label: "Tenant ID", in: "credentials" },
    { key: "client_id", label: "Client ID", in: "credentials" },
    { key: "client_secret", label: "Client secret", in: "credentials", secret: true },
  ] },
  { id: "azure_app_insights", blurb: "OpenTelemetry GenAI traces from Application Insights / Log Analytics.", auth: "API key with Application ID, or AAD with Workspace ID.", fields: [
    { key: "application_id", label: "Application ID", placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", in: "config" },
    { key: "workspace_id", label: "Log Analytics workspace ID", placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", in: "config", hint: "Only for AAD authentication." },
    { key: "api_key", label: "API key", in: "credentials", secret: true },
    { key: "tenant_id", label: "Tenant ID", in: "credentials" },
    { key: "client_id", label: "Client ID", in: "credentials" },
    { key: "client_secret", label: "Client secret", in: "credentials", secret: true },
  ] },
  { id: "azure_foundry", blurb: "Agent runs and model usage from Azure AI Foundry projects.", auth: "Service principal recommended; project API key as fallback.", fields: [
    { key: "endpoint", label: "Foundry project endpoint", placeholder: "https://<resource>.services.ai.azure.com/api/projects/<project>", in: "config", required: true },
    { key: "api_version", label: "API version", placeholder: "2024-05-01-preview", in: "config" },
    { key: "resource_id", label: "Azure resource ID", placeholder: "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<hub>", in: "config", hint: "For Azure Monitor metrics." },
    { key: "tenant_id", label: "Tenant ID", in: "credentials" },
    { key: "client_id", label: "Client ID", in: "credentials" },
    { key: "client_secret", label: "Client secret", in: "credentials", secret: true },
    { key: "api_key", label: "Project API key (fallback)", in: "credentials", secret: true },
  ] },
  { id: "aws_bedrock", blurb: "Invocation metrics and cost from Amazon Bedrock.", auth: "IAM user or role with CloudWatch read access.", fields: [
    { key: "region", label: "AWS region", placeholder: "us-east-1", in: "config", required: true },
    { key: "account_id", label: "AWS account ID", placeholder: "123456789012", in: "config" },
    { key: "access_key_id", label: "Access key ID", placeholder: "AKIA…", in: "credentials", required: true },
    { key: "secret_access_key", label: "Secret access key", in: "credentials", secret: true, required: true },
  ] },
  { id: "gcp_vertex", blurb: "Google Vertex AI usage.", soon: true, fields: [] },
  { id: "databricks_mlflow", blurb: "Databricks model serving and MLflow traces.", soon: true, fields: [] },
];

function statusOf(c: Connector): { tone: "accent" | "danger" | "wait" | undefined; label: string } {
  if (!c.is_active) return { tone: undefined, label: "Paused" };
  if (!c.last_sync_at) return { tone: "wait", label: "Never synced" };
  if ((c.last_sync_status ?? "").toLowerCase().includes("error") || c.last_sync_error) return { tone: "danger", label: "Sync failed" };
  return { tone: "accent", label: "Healthy" };
}

function ConnectorForm({ open, onClose, editing }: { open: boolean; onClose: () => void; editing: Connector | null }) {
  const create = useCreateConnector();
  const update = useUpdateConnector();
  const projects = useProjects();
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const toast = useToast();
  const [provider, setProvider] = useState<ConnectorProvider | null>(null);
  const [name, setName] = useState("");
  const [project, setProject] = useState("");
  const [interval, setIntervalV] = useState("10");
  const [values, setValues] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const sig = open ? (editing?.id ?? "new") : null;
  const [prevSig, setPrevSig] = useState<string | null>(null);
  if (sig !== prevSig) {
    setPrevSig(sig);
    if (sig) {
    setErr(null);
    setProvider(editing?.provider ?? null);
    setName(editing?.name ?? "");
    setProject(editing?.project_id ?? "");
    setIntervalV(String(editing?.sync_interval_minutes ?? 10));
    setValues(Object.fromEntries(Object.entries(editing?.config ?? {}).map(([k, v]) => [k, String(v ?? "")])));
    }
  }
  const def = PROVIDERS.find((p) => p.id === provider);
  const busy = create.isPending || update.isPending;

  const submit = async () => {
    if (!def) return;
    setErr(null);
    if (name.trim().length < 1) return setErr("Name the connector, e.g. “Production Azure OpenAI”.");
    const missing = def.fields.filter((f) => f.required && !values[f.key]?.trim() && !(editing && f.in === "credentials"));
    if (missing.length) return setErr(`Fill in ${missing.map((f) => f.label).join(", ")}.`);
    const config: Record<string, string> = {}, credentials: Record<string, string> = {};
    def.fields.forEach((f) => { const v = values[f.key]?.trim(); if (v) (f.in === "config" ? config : credentials)[f.key] = v; });
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, body: { name: name.trim(), config, sync_interval_minutes: Number(interval) || 10, ...(Object.keys(credentials).length ? { credentials } : {}) } });
        toast("Connector saved");
      } else {
        await create.mutateAsync({ name: name.trim(), provider: def.id, project_id: project || null, config, credentials, sync_interval_minutes: Number(interval) || 10, is_active: true });
        toast("Connector added. Run a test to check the credentials.");
      }
      onClose();
    } catch (e) { setErr(errMsg(e)); }
  };

  return (
    <Modal open={open} onClose={onClose} wide title={editing ? `Edit ${editing.name}` : def ? `Connect ${providerName(def.id)}` : "Add a connector"}
      sub={def ? def.auth : "Pull telemetry from a cloud AI service. Secrets are encrypted before they're stored."}
      footer={def ? <>
        {!editing && <button type="button" className="btn" onClick={() => setProvider(null)}>Back</button>}
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={submit}>{busy ? "Saving…" : editing ? "Save changes" : "Add connector"}</button>
      </> : undefined}>
      {!def ? (
        <div className="grid-2">
          {PROVIDERS.map((p) => (
            <button key={p.id} type="button" className="card" disabled={p.soon} onClick={() => { setProvider(p.id); if (!name) setName(providerName(p.id)); }}
              style={{ padding: 14, textAlign: "left", flexDirection: "row", gap: 12, alignItems: "flex-start", opacity: p.soon ? 0.55 : 1, cursor: p.soon ? "not-allowed" : "pointer" }}>
              <span className="ico" style={{ width: 32, height: 32, borderRadius: 9, display: "grid", placeItems: "center", background: "var(--accent-soft)", color: "var(--accent-text)", flex: "none" }}><Cloud className="ic" /></span>
              <span className="stack-sm" style={{ gap: 3 }}>
                <span className="row"><b>{providerName(p.id)}</b>{p.soon && <Pill>Coming soon</Pill>}</span>
                <span className="small muted">{p.blurb}</span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <>
          <div className="field-row">
            <div className="field"><label htmlFor="cn-name">Connector name</label><input id="cn-name" className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="field"><label htmlFor="cn-int">Sync every (minutes)</label><input id="cn-int" className="input" inputMode="numeric" value={interval} onChange={(e) => setIntervalV(e.target.value)} /></div>
          </div>
          {!editing && (
            <div className="field"><label htmlFor="cn-proj">Attribute spans to project</label>
              <select id="cn-proj" className="select-native" value={project} onChange={(e) => setProject(e.target.value)}>
                <option value="">Default project</option>
                {(projects.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{labels[p.id]}</option>)}
              </select>
            </div>
          )}
          <div className="card-t" style={{ fontSize: 12.5, marginTop: 4 }}>Connection</div>
          <div className="field-row">
            {def.fields.filter((f) => f.in === "config").map((f) => (
              <div className="field" key={f.key} style={f.key === "resource_id" || f.key === "endpoint" ? { gridColumn: "1 / -1" } : undefined}>
                <label htmlFor={`cf-${f.key}`}>{f.label}{f.required && " *"}</label>
                <input id={`cf-${f.key}`} className="input" value={values[f.key] ?? ""} placeholder={f.placeholder} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
                {f.hint && <span className="hint">{f.hint}</span>}
              </div>
            ))}
          </div>
          <div className="card-t" style={{ fontSize: 12.5, marginTop: 4 }}>Credentials</div>
          {editing && <div className="banner"><span>Stored: {editing.credential_keys.length ? editing.credential_keys.join(", ") : "none"}. Leave these empty to keep them; anything you type replaces the stored set.</span></div>}
          <div className="field-row">
            {def.fields.filter((f) => f.in === "credentials").map((f) => (
              <div className="field" key={f.key}>
                <label htmlFor={`cr-${f.key}`}>{f.label}{f.required && !editing && " *"}</label>
                <input id={`cr-${f.key}`} className="input" type={f.secret ? "password" : "text"} autoComplete="off" value={values[f.key] ?? ""} placeholder={f.placeholder ?? (f.secret ? "••••••••••••" : "")} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
              </div>
            ))}
          </div>
          {err && <div className="banner bad" role="alert">{err}</div>}
        </>
      )}
    </Modal>
  );
}

export default function ConnectorsPage() {
  const { data, isLoading, isError, error, refetch } = useConnectors();
  const projects = useProjects();
  const labels = useMemo(() => projectLabels(projects.data?.items ?? []), [projects.data]);
  const test = useTestConnector();
  const sync = useSyncConnector();
  const del = useDeleteConnector();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Connector | null>(null);
  const [confirm, setConfirm] = useState<Connector | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const list = data ?? [];
  const healthy = list.filter((c) => statusOf(c).tone === "accent").length;
  const failing = list.filter((c) => statusOf(c).tone === "danger").length;
  const records = list.reduce((a, c) => a + (c.last_sync_records ?? 0), 0);

  return (
    <>
      <PageHead title="Connectors" sub="Pull telemetry from cloud AI services you already run. The SDK is not required for these."
        actions={<button type="button" className="btn btn-primary" onClick={() => { setEditing(null); setOpen(true); }}><Plus className="ic" aria-hidden />Add connector</button>} />

      <section className="kpis" style={{ ["--cols" as string]: 4 } as React.CSSProperties} aria-label="Connector figures">
        <Kpi icon={Plug} label="Connectors" value={isLoading ? "—" : String(list.length)} foot={`${list.filter((c) => c.is_active).length} active`} />
        <Kpi icon={CircleCheck} label="Healthy" value={isLoading ? "—" : String(healthy)} foot="Last sync succeeded" />
        <Kpi icon={TriangleAlert} label="Failing" tone={failing ? "bad" : undefined} value={isLoading ? "—" : String(failing)} foot={failing ? "Check credentials and permissions" : "No sync errors"} />
        <Kpi icon={Zap} label="Records last sync" value={isLoading ? "—" : compact(records)} foot="Spans written across all connectors" />
      </section>

      <Card labelledBy="t-cn">
        <CardHeader id="t-cn" title="Connected services" sub="Test checks credentials live; Sync now pulls the latest data immediately." />
        <div style={{ marginTop: 12 }}>
          {isError ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading ? <SkelRows rows={4} /> : !list.length ? (
            <Empty icon={Plug} title="No connectors yet" action={<button type="button" className="btn btn-primary" onClick={() => { setEditing(null); setOpen(true); }}><Plus className="ic" aria-hidden />Add connector</button>}>
              Connect Azure OpenAI, Azure AI Foundry, App Insights or AWS Bedrock to see their usage next to SDK traces.
            </Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead><tr><th>Connector</th><th>Project</th><th>Status</th><th className="r">Last sync</th><th className="r">Records</th><th className="r">Every</th><th className="r"><span className="sr">Actions</span></th></tr></thead>
                <tbody>
                  {list.map((c) => {
                    const st = statusOf(c);
                    return (
                      <tr key={c.id}>
                        <td><div className="cell-main"><span className="ico" aria-hidden><Cloud className="ic" /></span><div><b>{c.name}</b><small>{providerName(c.provider)}</small></div></div></td>
                        <td className="muted">{c.project_id ? labels[c.project_id] ?? "Unnamed project" : "Default"}</td>
                        <td><Pill tone={st.tone} dot>{st.label}</Pill>{c.last_sync_error && <div className="sub" style={{ color: "var(--danger)", maxWidth: 280 }} title={c.last_sync_error}>{c.last_sync_error.slice(0, 80)}</div>}</td>
                        <td className="r muted">{c.last_sync_at ? ago(c.last_sync_at) : "Never"}</td>
                        <td className="r">{c.last_sync_records != null ? compact(c.last_sync_records) : "—"}</td>
                        <td className="r muted">{c.sync_interval_minutes} min</td>
                        <td className="r nowrap">
                          <button type="button" className="btn btn-sm" disabled={busy === c.id + "t"} onClick={async () => {
                            setBusy(c.id + "t");
                            try { const r = await test.mutateAsync(c.id); toast(r.success ? `Connected: ${r.message}` : r.message, !r.success); } catch (e) { toast(errMsg(e), true); }
                            setBusy(null);
                          }}>{busy === c.id + "t" ? "Testing…" : "Test"}</button>{" "}
                          <button type="button" className={`btn btn-sm${busy === c.id + "s" ? " spin" : ""}`} disabled={busy === c.id + "s"} onClick={async () => {
                            setBusy(c.id + "s");
                            try { const r = await sync.mutateAsync(c.id); toast(`${r.message} (${compact(r.records_written)} records)`, r.status === "error"); } catch (e) { toast(errMsg(e), true); }
                            setBusy(null);
                          }}><RefreshCw className="ic" aria-hidden />Sync now</button>{" "}
                          <button type="button" className="icon-btn sm" aria-label={`Edit ${c.name}`} onClick={() => { setEditing(c); setOpen(true); }}><Pencil className="ic" style={{ width: 14, height: 14 }} /></button>
                          <button type="button" className="icon-btn sm" aria-label={`Delete ${c.name}`} onClick={() => setConfirm(c)}><Trash2 className="ic" style={{ width: 14, height: 14 }} /></button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      <ConnectorForm open={open} onClose={() => setOpen(false)} editing={editing} />
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={`Delete ${confirm?.name ?? "connector"}?`} sub="Syncing stops and the stored credentials are removed. Spans already collected stay."
        footer={<><button type="button" className="btn" onClick={() => setConfirm(null)}>Cancel</button><button type="button" className="btn btn-primary" style={{ background: "var(--danger)" }} disabled={del.isPending}
          onClick={async () => { try { await del.mutateAsync(confirm!.id); toast("Connector deleted"); setConfirm(null); } catch (e) { toast(errMsg(e), true); } }}>Delete connector</button></>}>
        <p className="muted">You can add it again later with fresh credentials.</p>
      </Modal>
    </>
  );
}
