"use client";
import { useState } from "react";
import { Modal, errMsg, useToast } from "@/components/ui";
import { useCreateProject, useUpdateProject, type CaptureMode, type Project } from "@/lib/api";

const slugify = (s: string) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 100);

export const CAPTURE_LABEL: Record<CaptureMode, string> = {
  masked: "Masked: PII redacted",
  full: "Full: prompts and responses",
  disabled: "Off: no content stored",
};

/** Create (no project) or edit (with project) a project via the Admin service. */
export function ProjectForm({ open, onClose, project, onSaved }: { open: boolean; onClose: () => void; project?: Project; onSaved?: (p: Project) => void }) {
  const create = useCreateProject();
  const update = useUpdateProject(project?.id ?? "");
  const toast = useToast();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [desc, setDesc] = useState("");
  const [mode, setMode] = useState<CaptureMode>("masked");
  const [budget, setBudget] = useState("");
  const [active, setActive] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const sig = open ? (project?.id ?? "new") : null;
  const [prevSig, setPrevSig] = useState<string | null>(null);
  if (sig !== prevSig) {
    setPrevSig(sig);
    if (sig) {
    setName(project?.name ?? ""); setSlug(project?.slug ?? ""); setSlugTouched(!!project);
    setDesc(project?.description ?? ""); setMode(project?.content_capture_mode ?? "masked");
    setBudget(project?.monthly_budget_usd != null ? String(project.monthly_budget_usd) : ""); setActive(project?.is_active ?? true); setErr(null);
    }
  }

  const busy = create.isPending || update.isPending;
  const submit = async () => {
    setErr(null);
    if (name.trim().length < 2) return setErr("Give the project a name of at least 2 characters.");
    if (!project && !/^[a-z0-9-]{2,100}$/.test(slug)) return setErr("The slug can use lowercase letters, numbers and dashes (2+ characters).");
    const b = budget.trim() ? Number(budget) : null;
    if (b != null && (Number.isNaN(b) || b < 0)) return setErr("The monthly budget must be a positive number.");
    try {
      const saved = project
        ? await update.mutateAsync({ name: name.trim(), description: desc.trim() || null, content_capture_mode: mode, monthly_budget_usd: b, is_active: active })
        : await create.mutateAsync({ name: name.trim(), slug, description: desc.trim() || null, content_capture_mode: mode, monthly_budget_usd: b, tags: [] });
      toast(project ? "Project saved" : `Project “${saved.name}” created`);
      onSaved?.(saved);
      onClose();
    } catch (e) { setErr(errMsg(e)); }
  };

  return (
    <Modal open={open} onClose={onClose} title={project ? "Edit project" : "New project"}
      sub={project ? project.slug : "Projects group the agents and API keys of one AI application."}
      footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button><button type="button" className="btn btn-primary" disabled={busy} onClick={submit}>{busy ? "Saving…" : project ? "Save changes" : "Create project"}</button></>}>
      <div className="field">
        <label htmlFor="pf-name">Name</label>
        <input id="pf-name" className="input" value={name} placeholder="Customer support agent"
          onChange={(e) => { setName(e.target.value); if (!slugTouched && !project) setSlug(slugify(e.target.value)); }} />
      </div>
      {!project && (
        <div className="field">
          <label htmlFor="pf-slug">Slug</label>
          <input id="pf-slug" className="input" value={slug} onChange={(e) => { setSlug(e.target.value); setSlugTouched(true); }} placeholder="customer-support-agent" />
          <span className="hint">Used in URLs and the SDK. Lowercase letters, numbers and dashes.</span>
        </div>
      )}
      <div className="field">
        <label htmlFor="pf-desc">Description</label>
        <textarea id="pf-desc" className="textarea" rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What this application does and who uses it" />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor="pf-mode">Content capture</label>
          <select id="pf-mode" className="select-native" value={mode} onChange={(e) => setMode(e.target.value as CaptureMode)}>
            {(Object.keys(CAPTURE_LABEL) as CaptureMode[]).map((m) => <option key={m} value={m}>{CAPTURE_LABEL[m]}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pf-budget">Monthly budget (USD)</label>
          <input id="pf-budget" className="input" inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="Optional, e.g. 500" />
        </div>
      </div>
      {project && <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />Project is active</label>}
      {err && <div className="banner bad" role="alert"><span>{err}</span></div>}
    </Modal>
  );
}
