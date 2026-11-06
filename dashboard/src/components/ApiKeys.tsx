"use client";
import { useState } from "react";
import { KeyRound, Plus, TriangleAlert } from "lucide-react";
import { Card, CardHeader, CopyButton, Empty, ErrorState, Modal, Pill, SkelRows, errMsg, useToast } from "@/components/ui";
import { useApiKeys, useCreateApiKey, useRevokeApiKey, type ApiKeyCreated } from "@/lib/api";
import { ago, day } from "@/lib/format";

/** List, create and revoke ingestion keys for one project (Admin service). */
export function ApiKeysCard({ projectId, compact }: { projectId: string; compact?: boolean }) {
  const keys = useApiKeys(projectId);
  const create = useCreateApiKey(projectId);
  const revoke = useRevokeApiKey();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    if (!name.trim()) return setErr("Name the key so you can recognise it later, e.g. “production server”.");
    try { setCreated(await create.mutateAsync({ name: name.trim(), scopes: ["ingest"] })); setName(""); }
    catch (e) { setErr(errMsg(e)); }
  };

  return (
    <Card labelledBy={`keys-${projectId}`}>
      <CardHeader id={`keys-${projectId}`} title="API keys" sub="Used by the SDK to send telemetry. The full key is shown once." bordered
        action={<button type="button" className="btn btn-sm" onClick={() => { setOpen(true); setCreated(null); setErr(null); }}><Plus className="ic" aria-hidden />New key</button>} />
      {keys.isError ? <ErrorState error={keys.error} onRetry={() => keys.refetch()} /> : keys.isLoading ? <SkelRows rows={3} /> : !keys.data?.length ? (
        <Empty icon={KeyRound} title="No keys yet">Create a key, then pass it to <b>trustai.init(api_key=…)</b>.</Empty>
      ) : (
        <div className="scroll-x">
          <table>
            <thead><tr><th>Name</th><th>Key</th><th>Status</th>{!compact && <th>Scopes</th>}<th>Last used</th>{!compact && <th>Created</th>}<th className="r"><span className="sr">Actions</span></th></tr></thead>
            <tbody>
              {keys.data.map((k) => (
                <tr key={k.id}>
                  <td className="strong">{k.name}</td>
                  <td className="muted">{k.key_prefix}…</td>
                  <td><Pill tone={k.status === "active" ? "accent" : k.status === "revoked" ? "danger" : undefined} dot>{k.status === "active" ? "Active" : k.status === "revoked" ? "Revoked" : "Expired"}</Pill></td>
                  {!compact && <td className="muted">{k.scopes.join(", ")}</td>}
                  <td className="muted">{k.last_used_at ? ago(k.last_used_at) : "Never"}</td>
                  {!compact && <td className="muted">{day(k.created_at)}</td>}
                  <td className="r">{k.status === "active" && <button type="button" className="btn btn-sm btn-danger" onClick={() => setConfirm(k.id)}>Revoke</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={created ? "Copy your new key" : "New API key"}
        sub={created ? "This is the only time the full key is shown." : "Keys are scoped to ingestion for this project."}
        footer={created
          ? <button type="button" className="btn btn-primary" onClick={() => setOpen(false)}>Done</button>
          : <><button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button><button type="button" className="btn btn-primary" disabled={create.isPending} onClick={submit}>{create.isPending ? "Creating…" : "Create key"}</button></>}>
        {created ? (
          <>
            <div className="secret"><span className="grow" style={{ overflowWrap: "anywhere" }}>{created.raw_key}</span><CopyButton text={created.raw_key} /></div>
            <div className="banner wait"><TriangleAlert className="ic" aria-hidden /><span>Store it in your secret manager now. TrustAI keeps only a hash and can&apos;t show it again.</span></div>
          </>
        ) : (
          <>
            <div className="field"><label htmlFor="ak-name">Key name</label><input id="ak-name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Production server" onKeyDown={(e) => { if (e.key === "Enter") submit(); }} /></div>
            {err && <div className="banner bad" role="alert">{err}</div>}
          </>
        )}
      </Modal>

      <Modal open={!!confirm} onClose={() => setConfirm(null)} title="Revoke this key?" sub="Apps using it stop sending telemetry immediately. This can't be undone."
        footer={<><button type="button" className="btn" onClick={() => setConfirm(null)}>Cancel</button>
          <button type="button" className="btn btn-primary" style={{ background: "var(--danger)" }} disabled={revoke.isPending} onClick={async () => {
            try { await revoke.mutateAsync(confirm!); toast("Key revoked"); setConfirm(null); } catch (e) { toast(errMsg(e), true); }
          }}>Revoke key</button></>}>
        <p className="muted">Create a replacement first if a running service still needs access.</p>
      </Modal>
    </Card>
  );
}
