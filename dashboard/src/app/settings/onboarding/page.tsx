"use client";
import { useMemo, useState } from "react";
import { FolderKanban, Plus } from "lucide-react";
import { ApiKeysCard } from "@/components/ApiKeys";
import { ProjectForm } from "@/components/ProjectForm";
import { Card, CardHeader, ChipSelect, CopyButton, Empty, PageHead, SkelRows } from "@/components/ui";
import { useProjects } from "@/lib/api";
import { projectLabels } from "@/lib/projects";

const INGEST = process.env.NEXT_PUBLIC_INGESTION_URL || "http://localhost:8001";

function Code({ code }: { code: string }) {
  return <div className="code" style={{ paddingRight: 90 }}><span className="copy"><CopyButton text={code} /></span>{code}</div>;
}

export default function OnboardingPage() {
  const projects = useProjects();
  const items = useMemo(() => projects.data?.items ?? [], [projects.data]);
  const labels = useMemo(() => projectLabels(items), [items]);
  const [pick, setPid] = useState("");
  const [open, setOpen] = useState(false);
  const project = items.find((p) => p.id === pick) ?? items[0];
  const pid = project?.id ?? "";

  const init = `import trustai

trustai.init(
    api_key="tai_live_…",          # from the API keys card above
    project_id="${pid || "<project-uuid>"}",
    environment="production",
    ingest_url="${INGEST}",
    content_capture_mode="${project?.content_capture_mode ?? "masked"}",  # "full" | "masked" | "disabled"
)`;
  const use = `@trustai.llm_call(model="gpt-4o", provider="azure_openai")
def call_llm(prompt: str):
    return client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])

@trustai.agent("customer_support_agent")
def run_agent(query: str):
    return call_llm(query).choices[0].message.content`;

  return (
    <>
      <PageHead title="SDK & API keys" sub="Instrument a Python app in three steps. Spans appear in Traces within seconds."
        actions={<>
          {items.length > 0 && <ChipSelect label="Project" value={pid} onChange={setPid} options={items.map((p) => ({ value: p.id, label: labels[p.id] }))} />}
          <button type="button" className="btn" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />New project</button>
        </>} />

      <ol className="steps" aria-label="Setup steps" style={{ maxWidth: 720 }}>
        <li className={pid ? "done" : "cur"}><span className="n">1</span>Pick a project</li>
        <li className={pid ? "cur" : ""}><span className="n">2</span>Create an API key</li>
        <li><span className="n">3</span>Add the SDK</li>
      </ol>

      {projects.isLoading ? <Card><SkelRows rows={4} /></Card> : !items.length ? (
        <Card><Empty icon={FolderKanban} title="Create a project first" action={<button type="button" className="btn btn-primary" onClick={() => setOpen(true)}><Plus className="ic" aria-hidden />New project</button>}>Each AI application gets its own project, keys and cost tracking.</Empty></Card>
      ) : (
        <div className="split-r">
          <div className="stack">
            {pid && <ApiKeysCard projectId={pid} compact />}
            <Card>
              <CardHeader title="Project details" sub="Values the SDK needs" bordered />
              <div className="card-b">
                <dl className="kv">
                  <dt>Project</dt><dd>{project ? labels[project.id] : "—"}</dd>
                  <dt>Project ID</dt><dd>{pid}</dd>
                  <dt>Content capture</dt><dd>{project?.content_capture_mode ?? "—"}</dd>
                  <dt>Ingestion URL</dt><dd>{INGEST}</dd>
                </dl>
              </div>
            </Card>
          </div>
          <Card>
            <CardHeader title="Add the SDK" sub="Python 3.11+" bordered />
            <div className="card-b stack">
              <div className="stack-sm"><b>1. Install</b><Code code="pip install ./trustai-sdk" /></div>
              <div className="stack-sm"><b>2. Initialise once at start-up</b><Code code={init} /></div>
              <div className="stack-sm"><b>3. Decorate your LLM calls and agents</b><Code code={use} />
                <span className="small muted">Tokens, cost, latency and (masked) content are captured automatically. See docs/TRUSTAI_SDK_DEVELOPER_GUIDE.md for tools, RAG and multi-turn agents.</span></div>
            </div>
          </Card>
        </div>
      )}
      <ProjectForm open={open} onClose={() => setOpen(false)} onSaved={(p) => setPid(p.id)} />
    </>
  );
}
