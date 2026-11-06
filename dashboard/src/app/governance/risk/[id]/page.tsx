"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Check, Gavel, Save, Send, TriangleAlert } from "lucide-react";
import { AssessmentBadge, DecisionBadge, TIER_LABEL } from "@/components/gov";
import { Card, CardHeader, ErrorState, PageHead, Skel, SkelRows, errMsg, useToast } from "@/components/ui";
import { fmtValue, useAgent, useAssessment, useDecide, useRiskTemplate, useSaveAnswers, useSubmitAssessment, type Assessment, type Decision, type TemplateQuestion } from "@/lib/governance";
import { when } from "@/lib/format";

const TIER_C: Record<number, string> = { 1: "var(--accent)", 2: "var(--c2)", 3: "var(--c3)", 4: "var(--danger)" };

export default function AssessmentPage() {
  const { id } = useParams<{ id: string }>();
  const as = useAssessment(id);
  const tpl = useRiskTemplate();
  const a = as.data;
  const agent = useAgent(a?.agent_id ?? "");
  const save = useSaveAnswers(id);
  const submit = useSubmitAssessment(id);
  const toast = useToast();
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  // Reset the local draft whenever the server copy changes (after load, save or submit).
  const version = a ? `${a.id}:${a.updated_at}` : null;
  const [seen, setSeen] = useState<string | null>(null);
  if (a && version !== seen) { setSeen(version); setDraft(a.answers ?? {}); }
  const frozen = a?.status === "decided";
  const dirty = useMemo(() => a ? Object.keys(draft).some((k) => JSON.stringify(draft[k]) !== JSON.stringify(a.answers?.[k])) : false, [draft, a]);
  const questions = useMemo(() => tpl.data?.sections.flatMap((s) => s.questions) ?? [], [tpl.data]);
  const answered = questions.filter((q) => draft[q.id] !== undefined && draft[q.id] !== null).length;
  const missingRequired = questions.filter((q) => q.required && (draft[q.id] === undefined || draft[q.id] === null));
  const prov = a?.evidence?.provenance ?? {};

  const changed = () => Object.fromEntries(Object.entries(draft).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(a?.answers?.[k])));
  const doSave = () => save.mutate(changed(), { onSuccess: () => toast("Answers saved"), onError: (e) => toast(errMsg(e), true) });
  const doSubmit = async (fillDefaults: boolean) => {
    try {
      if (dirty) await save.mutateAsync(changed());
      const r = await submit.mutateAsync({ fillDefaults });
      toast(`Classified as Tier ${r.risk_tier} · ${TIER_LABEL[r.risk_tier ?? 1]}`);
    } catch (e) { toast(errMsg(e), true); }
  };

  if (as.isError) return <Card><ErrorState error={as.error} onRetry={() => as.refetch()} /></Card>;

  return (
    <>
      <PageHead
        kicker={<Link href="/governance/risk" className="row small muted"><ArrowLeft className="ic" style={{ width: 14, height: 14 }} aria-hidden />Risk assessments</Link>}
        title={a ? <span className="row" style={{ gap: 10 }}>{agent.data?.name ?? "Assessment"}<AssessmentBadge status={a.status} /></span> : <Skel w={260} h={24} />}
        sub={a ? <>Started {when(a.created_at)} by {a.created_by}{agent.data && <> · <Link href={`/governance/agents/${a.agent_id}`} className="strong" style={{ color: "var(--accent-text)" }}>Open agent</Link></>}</> : undefined}
        actions={a && !frozen && <>
          <button type="button" className="btn" disabled={!dirty || save.isPending} onClick={doSave}><Save className="ic" aria-hidden />{save.isPending ? "Saving…" : "Save"}</button>
          <button type="button" className="btn btn-primary" disabled={submit.isPending} onClick={() => doSubmit(true)}><Send className="ic" aria-hidden />{submit.isPending ? "Classifying…" : a.status === "classified" && !dirty ? "Re-classify" : "Submit & classify"}</button>
        </>} />

      <div className="split-wide" style={{ alignItems: "start" }}>
        <Card labelledBy="t-q">
          <CardHeader id="t-q" title="Questionnaire" bordered
            sub={tpl.data ? `${answered} of ${questions.length} answered${missingRequired.length ? ` · ${missingRequired.length} required left` : ""}` : "Loading…"}
            action={tpl.data && <span className="row small muted" style={{ gap: 10 }}><span className="bar-track" style={{ width: 120 }} aria-hidden><i style={{ width: `${questions.length ? (answered / questions.length) * 100 : 0}%` }} /></span><b className="num" style={{ color: "var(--text)" }}>{questions.length ? Math.round((answered / questions.length) * 100) : 0}%</b></span>} />
          <div className="card-b">
            {frozen && <div className="banner"><Check className="ic" aria-hidden /><span>This assessment is decided and frozen. Start a new one from the agent page to change answers.</span></div>}
            {!a || tpl.isLoading ? <SkelRows rows={10} /> : tpl.data?.sections.map((s) => (
              <div key={s.title} className="q-sec">
                <h3>{s.title}</h3>
                {s.questions.map((q) => (
                  <Question key={q.id} q={q} value={draft[q.id]} source={prov[q.id]} disabled={frozen}
                    onChange={(v) => setDraft((d) => ({ ...d, [q.id]: v }))} />
                ))}
              </div>
            ))}
          </div>
        </Card>

        <div className="stack">
          <ResultCard a={a} />
          {a && (a.status === "classified" || a.status === "decided") && <Decide a={a} />}
        </div>
      </div>
    </>
  );
}

function ResultCard({ a }: { a: Assessment | undefined }) {
    if (!a) return <Card><SkelRows rows={4} /></Card>;
    const classified = a.risk_tier != null && (a.status === "classified" || a.status === "decided");
    const reasons = a.tier_reasons.filter((r) => r.points != null).sort((x, y) => Math.abs(y.points ?? 0) - Math.abs(x.points ?? 0));
    const floors = a.tier_reasons.filter((r) => r.floor);
    const max = Math.max(1, ...reasons.map((r) => Math.abs(r.points ?? 0)));
    const assumptions = a.evidence?.assumptions ?? [];
    return (
      <Card labelledBy="t-res">
        <CardHeader id="t-res" title="Classification" bordered sub={classified ? `Score ${a.risk_score} · tiers break at 20, 40 and 75` : "Submit to see the tier"} />
        <div className="card-b" style={{ gap: 14 }}>
          {!classified ? <p className="small muted" style={{ margin: 0 }}>Unanswered questions take conservative defaults on submit; each assumption is recorded as evidence.</p> : (
            <>
              <div className="row" style={{ gap: 12 }}>
                <span style={{ width: 44, height: 44, borderRadius: 12, display: "grid", placeItems: "center", background: TIER_C[a.risk_tier!], color: "#fff", fontWeight: 700, fontSize: 18 }}>{a.risk_tier}</span>
                <div><b style={{ fontSize: 15 }}>Tier {a.risk_tier} · {TIER_LABEL[a.risk_tier!]}</b><div className="small muted">{a.required_controls.length} required controls</div></div>
              </div>
              <div className="row" style={{ gap: 3 }} aria-label="Tier scale">
                {[1, 2, 3, 4].map((t) => <i key={t} style={{ flex: 1, height: 6, borderRadius: 3, background: t <= a.risk_tier! ? TIER_C[t] : "var(--hover)" }} />)}
              </div>
              {floors.map((f, i) => <div key={i} className="banner wait"><TriangleAlert className="ic" aria-hidden /><span>{f.floor}</span></div>)}
              <section>
                <h3 className="small strong" style={{ margin: "0 0 8px" }}>What drove the score</h3>
                <ul className="stack-sm">{reasons.slice(0, 8).map((r) => (
                  <li key={r.question} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 80px 34px", gap: 10, alignItems: "center" }}>
                    <span className="small ellipsis" title={r.label}>{r.label}</span>
                    <span className="bar-track"><i style={{ width: `${(Math.abs(r.points ?? 0) / max) * 100}%`, background: (r.points ?? 0) < 0 ? "var(--accent)" : "var(--c3)" }} /></span>
                    <b className="small num r" style={{ color: (r.points ?? 0) < 0 ? "var(--accent-text)" : undefined }}>{(r.points ?? 0) > 0 ? "+" : ""}{r.points}</b>
                  </li>))}</ul>
              </section>
              <section>
                <h3 className="small strong" style={{ margin: "0 0 6px" }}>Required controls</h3>
                <ul className="checklist">{a.required_controls.map((c) => <li key={c}><span className="ci" aria-hidden><Check /></span><span>{c}</span><span /></li>)}</ul>
              </section>
              {assumptions.length > 0 && <p className="small muted" style={{ margin: 0 }}>{assumptions.length} {assumptions.length === 1 ? "answer was" : "answers were"} assumed from defaults: {assumptions.map((x) => x.label).slice(0, 3).join("; ")}{assumptions.length > 3 ? "…" : ""}</p>}
            </>
          )}
        </div>
      </Card>
    );
  }

function Decide({ a }: { a: Assessment }) {
    const decide = useDecide(a.id);
    const toast = useToast();
    const [choice, setChoice] = useState<Decision>("approved");
    const [conditions, setConditions] = useState("");
    const [note, setNote] = useState("");
    if (a.status === "decided") {
      return (
        <Card labelledBy="t-dec">
          <CardHeader id="t-dec" title="Decision" bordered sub={`${a.decided_by} · ${when(a.decided_at)}`} action={<DecisionBadge decision={a.decision} />} />
          <div className="card-b">
            {a.conditions.length > 0 && <ul className="small" style={{ margin: 0, paddingLeft: 16, listStyle: "disc", lineHeight: 1.7 }}>{a.conditions.map((c) => <li key={c}>{c}</li>)}</ul>}
            {a.decision_note && <p className="small muted" style={{ margin: 0 }}>&ldquo;{a.decision_note}&rdquo;</p>}
          </div>
        </Card>
      );
    }
    const conds = conditions.split("\n").map((c) => c.trim()).filter(Boolean);
    const go = () => decide.mutate({ decision: choice, conditions: choice === "approved_with_conditions" ? conds : [], note: note || undefined }, {
      onSuccess: () => toast("Decision recorded"), onError: (e) => toast(errMsg(e), true),
    });
    return (
      <Card labelledBy="t-dec">
        <CardHeader id="t-dec" title="Your decision" bordered sub="Only a person can approve; it's recorded in the audit trail." />
        <div className="card-b">
          <div className="seg" role="radiogroup" aria-label="Decision" style={{ width: "100%" }}>
            {([["approved", "Approve"], ["approved_with_conditions", "With conditions"], ["rejected", "Reject"]] as const).map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={choice === v} style={{ flex: 1 }} onClick={() => setChoice(v)}>{l}</button>
            ))}
          </div>
          {choice === "approved_with_conditions" && <div className="field"><label htmlFor="dc-cond">Conditions · one per line</label><textarea id="dc-cond" className="textarea" rows={3} value={conditions} onChange={(e) => setConditions(e.target.value)} placeholder="Human approval on refunds over $500" /></div>}
          <div className="field"><label htmlFor="dc-note">Note (optional)</label><textarea id="dc-note" className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></div>
          <button type="button" className={`btn ${choice === "rejected" ? "btn-danger" : "btn-primary"}`} disabled={decide.isPending || (choice === "approved_with_conditions" && !conds.length)} onClick={go}>
            <Gavel className="ic" aria-hidden />{decide.isPending ? "Recording…" : "Record decision"}
          </button>
        </div>
      </Card>
    );
}

function Question({ q, value, source, disabled, onChange }: { q: TemplateQuestion; value: unknown; source?: string; disabled?: boolean; onChange: (v: unknown) => void }) {
  const id = `q-${q.id}`;
  let input: React.ReactNode;
  if (q.type === "bool") {
    input = (
      <div className="seg sm" role="radiogroup" aria-labelledby={`${id}-l`}>
        {([[true, "Yes"], [false, "No"]] as const).map(([v, l]) => <button key={l} type="button" role="radio" aria-checked={value === v} disabled={disabled} onClick={() => onChange(v)}>{l}</button>)}
      </div>
    );
  } else if (q.type === "select") {
    input = (
      <select id={id} className="select-native" value={value == null ? "" : String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value || null)} aria-labelledby={`${id}-l`}>
        <option value="">Not answered</option>
        {q.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else if (q.type === "multi") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    input = (
      <div className="opt-row" role="group" aria-labelledby={`${id}-l`}>
        {q.options?.map((o) => {
          const on = arr.includes(o.value);
          return <button key={o.value} type="button" className="btn btn-sm" aria-pressed={on} disabled={disabled} onClick={() => onChange(on ? arr.filter((x) => x !== o.value) : [...arr, o.value])}>{o.label}</button>;
        })}
      </div>
    );
  } else {
    input = <input id={id} className="input" type="number" min={0} value={value == null ? "" : String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} aria-labelledby={`${id}-l`} style={{ maxWidth: 120 }} />;
  }
  return (
    <div className="q">
      <div>
        <div className="ql" id={`${id}-l`}>{q.label}{q.required && <span style={{ color: "var(--danger)" }} aria-label="required"> *</span>}</div>
        {q.help && <div className="qh">{q.help}</div>}
        {source && value !== undefined && <div className="src">{source.startsWith("answered by") ? source.replace("answered by", "Answered by") : `Pre-filled from ${source}`}</div>}
        {value === undefined && q.default !== undefined && <div className="qh">Default if left blank: {fmtValue(q.options?.find((o) => o.value === q.default)?.label ?? q.default)}</div>}
      </div>
      <div>{input}</div>
    </div>
  );
}
