"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CircleStop, Swords } from "lucide-react";
import { EvalBadge } from "@/components/gov";
import { Card, CardHeader, ChipSelect, Drawer, Empty, ErrorState, PageHead, Pill, Skel, SkelRows, StatStrip, errMsg, useToast } from "@/components/ui";
import { useAgent, useCancelEvaluation, useEvaluation, type Iteration, type IterationOutcome } from "@/lib/governance";
import { humanize, ms, when } from "@/lib/format";

const OUT: Record<IterationOutcome, [string, string, "accent" | "danger" | "wait" | "blue" | undefined]> = {
  blocked: ["Blocked", "var(--accent)", "accent"],
  answered: ["Answered", "var(--c2)", "blue"],
  complied: ["Complied", "var(--danger)", "danger"],
  over_blocked: ["Over-blocked", "var(--wait)", "wait"],
  error: ["Error", "var(--c5)", undefined],
};

export default function EvaluationPage() {
  const { id } = useParams<{ id: string }>();
  const ev = useEvaluation(id);
  const e = ev.data;
  const agent = useAgent(e?.agent_id ?? "");
  const cancel = useCancelEvaluation();
  const toast = useToast();
  const [outcome, setOutcome] = useState("");
  const [cat, setCat] = useState("");
  const [sel, setSel] = useState<Iteration | null>(null);
  const s = e?.summary ?? {};
  const its = useMemo(() => e?.iterations ?? [], [e]);
  const counts = useMemo(() => its.reduce<Record<string, number>>((m, i) => ({ ...m, [i.outcome]: (m[i.outcome] ?? 0) + 1 }), {}), [its]);
  const list = its.filter((i) => (!outcome || i.outcome === outcome) && (!cat || (i.category ?? "benign") === cat));
  const cats = Object.entries(s.by_category ?? {}).sort((a, b) => a[1].block_rate_pct - b[1].block_rate_pct);
  const live = e?.status === "running" || e?.status === "queued";

  if (ev.isError) return <Card><ErrorState error={ev.error} onRetry={() => ev.refetch()} /></Card>;

  return (
    <>
      <PageHead
        kicker={<Link href="/governance/evaluations" className="row small muted"><ArrowLeft className="ic" style={{ width: 14, height: 14 }} aria-hidden />Red-team runs</Link>}
        title={e ? <span className="row" style={{ gap: 10 }}>{agent.data?.name ?? "Red-team run"}<EvalBadge status={e.status} progress={e.progress} total={e.prompts_total} /></span> : <Skel w={260} h={24} />}
        sub={e ? <>{humanize(e.eval_type)} · started {when(e.created_at)} by {e.created_by}{agent.data && <> · <Link href={`/governance/agents/${e.agent_id}`} className="strong" style={{ color: "var(--accent-text)" }}>Open agent</Link></>}</> : undefined}
        actions={live && <button type="button" className="btn btn-danger" disabled={cancel.isPending} onClick={() => cancel.mutate(id, { onSuccess: () => toast("Run cancelled"), onError: (x) => toast(errMsg(x), true) })}><CircleStop className="ic" aria-hidden />Cancel run</button>} />

      {e?.error && <div className="banner bad" role="alert"><span><b>The run failed.</b> {e.error}</span></div>}

      <div className="split-l" style={{ alignItems: "stretch" }}>
        <Card labelledBy="t-sum">
          <CardHeader id="t-sum" title="Result" sub={live ? `Testing… ${e?.progress ?? 0} of ${e?.prompts_total ?? 0} prompts` : s.meets_threshold ? "Meets the release threshold" : e?.status === "completed" ? "Below the release threshold" : ""}
            action={e?.status === "completed" && <Pill tone={s.meets_threshold ? "accent" : "danger"} dot>{s.meets_threshold ? "Pass" : "Fail"}</Pill>} />
          <div className="card-b" style={{ gap: 16 }}>
            {!e ? <SkelRows rows={4} /> : (
              <>
                <div className="row" style={{ gap: 18, alignItems: "flex-end" }}>
                  <div><div className="small muted">Trust score</div><div style={{ fontSize: 30, fontWeight: 650, letterSpacing: "-.02em", lineHeight: 1.1 }} className="num">{e.trust_score != null ? e.trust_score.toFixed(1) : "—"}</div></div>
                  <div className="grow" style={{ paddingBottom: 6 }}>
                    <div style={{ position: "relative" }}>
                      <span className="bar-track" style={{ height: 8, display: "block" }}><i style={{ width: `${Math.max(0, Math.min(100, e.trust_score ?? 0))}%`, background: (e.trust_score ?? 0) >= (s.trust_threshold ?? 95) ? "var(--accent)" : "var(--danger)" }} /></span>
                      <i aria-hidden style={{ position: "absolute", top: -3, left: `${s.trust_threshold ?? 95}%`, width: 2, height: 14, borderRadius: 1, background: "var(--text)" }} />
                    </div>
                    <div className="small muted" style={{ marginTop: 6 }}>Pass mark {s.trust_threshold ?? 95} (marker)</div>
                  </div>
                </div>
                {live && <span className="bar-track" style={{ height: 8 }}><i style={{ width: `${e.prompts_total ? (e.progress / e.prompts_total) * 100 : 0}%` }} /></span>}
                <StatStrip items={[
                  ["Attacks blocked", s.block_rate_pct != null ? `${s.block_rate_pct.toFixed(1)}%` : "—"],
                  ["Over-blocked", s.false_positive_rate_pct != null ? `${s.false_positive_rate_pct.toFixed(1)}%` : "—"],
                  ["Harmful · benign", `${s.harmful_prompts ?? "—"} · ${s.benign_prompts ?? "—"}`],
                  ["Errors", String(s.errored ?? 0)],
                ]} />
                {its.length > 0 && (
                  <div className="stack-sm">
                    <div className="outcome-bar" aria-hidden>{(Object.keys(OUT) as IterationOutcome[]).map((o) => counts[o] ? <i key={o} style={{ flex: `${counts[o]} 1 0`, background: OUT[o][1] }} /> : null)}</div>
                    <div className="legend">{(Object.keys(OUT) as IterationOutcome[]).filter((o) => counts[o]).map((o) => <span key={o}><i style={{ background: OUT[o][1] }} />{OUT[o][0]} <b className="num">{counts[o]}</b></span>)}</div>
                  </div>
                )}
              </>
            )}
          </div>
        </Card>

        <Card labelledBy="t-cat">
          <CardHeader id="t-cat" title="By attack category" sub="Share of attacks blocked · weakest first" bordered />
          <div className="card-b">
            {!e ? <SkelRows rows={5} /> : !cats.length ? <p className="small muted" style={{ margin: 0 }}>{live ? "Categories appear as prompts are graded." : "No category breakdown."}</p> : (
              <ul className="stack-sm" style={{ gap: 10 }}>{cats.map(([c, st]) => (
                <li key={c} style={{ display: "grid", gridTemplateColumns: "140px minmax(0,1fr) 92px", gap: 12, alignItems: "center" }}>
                  <button type="button" className="small ellipsis" style={{ textAlign: "left", fontWeight: 500, color: cat === c ? "var(--accent-text)" : "var(--text-2)" }} onClick={() => setCat(cat === c ? "" : c)} title="Filter prompts">{humanize(c)}</button>
                  <span className="bar-track" style={{ height: 8 }}><i style={{ width: `${st.block_rate_pct}%`, background: st.block_rate_pct >= 95 ? "var(--accent)" : st.block_rate_pct >= 80 ? "var(--wait)" : "var(--danger)" }} /></span>
                  <span className="small num r"><b>{st.block_rate_pct.toFixed(0)}%</b> <span className="muted">{st.blocked}/{st.total}</span></span>
                </li>))}</ul>
            )}
          </div>
        </Card>
      </div>

      {!!s.per_guardrail?.length && (
        <Card labelledBy="t-gr">
          <CardHeader id="t-gr" title="Per guardrail" sub="How each guardrail would have graded the same prompts" />
          <div className="scroll-x" style={{ marginTop: 12 }}><table>
            <thead><tr><th>Guardrail</th><th className="r">Caught attacks (recall)</th><th className="r">False alarms</th><th className="r">True positives</th><th className="r">Missed</th><th className="r">False positives</th><th className="r">True negatives</th></tr></thead>
            <tbody>{s.per_guardrail.map((g) => (
              <tr key={g.guardrail_id}><td className="strong">{g.guardrail_name ?? "Guardrail"}</td><td className="r">{g.recall_pct != null ? `${g.recall_pct.toFixed(1)}%` : "—"}</td><td className="r">{g.false_positive_rate_pct != null ? `${g.false_positive_rate_pct.toFixed(1)}%` : "—"}</td><td className="r">{g.tp}</td><td className="r" style={{ color: g.fn ? "var(--danger)" : undefined }}>{g.fn}</td><td className="r">{g.fp}</td><td className="r">{g.tn}</td></tr>
            ))}</tbody>
          </table></div>
        </Card>
      )}

      <Card labelledBy="t-it">
        <CardHeader id="t-it" title="Prompts" sub={`${list.length} of ${its.length}`}
          action={<div className="filterbar">
            <ChipSelect label="Outcome" value={outcome} onChange={setOutcome} options={[{ value: "", label: "All" }, ...(Object.keys(OUT) as IterationOutcome[]).map((o) => ({ value: o, label: OUT[o][0] }))]} />
            <ChipSelect label="Category" value={cat} onChange={setCat} options={[{ value: "", label: "All" }, ...Object.keys(s.by_category ?? {}).map((c) => ({ value: c, label: humanize(c) }))]} />
          </div>} />
        <div style={{ marginTop: 12 }}>
          {!e ? <SkelRows rows={6} /> : !list.length ? <Empty icon={Swords} title={its.length ? "No prompts match" : live ? "Waiting for the first results" : "No prompts recorded"} /> : (
            <div className="scroll-y sticky-head" style={{ maxHeight: 480 }}><table>
              <thead><tr><th>Prompt</th><th>Type</th><th>Category</th><th>Strategy</th><th>Outcome</th><th className="r">Latency</th></tr></thead>
              <tbody>{list.map((i, n) => (
                <tr key={i.id ?? n} className="clickable" onClick={() => setSel(i)}>
                  <td style={{ maxWidth: 520 }}><span className="ellipsis" style={{ display: "block" }}>{i.prompt}</span></td>
                  <td>{i.harmful ? <span className="tag bad">Attack</span> : <span className="tag">Benign</span>}</td>
                  <td className="muted">{i.category ? humanize(i.category) : "—"}</td>
                  <td className="muted">{i.strategy ? humanize(i.strategy) : "—"}</td>
                  <td><Pill tone={OUT[i.outcome]?.[2]} dot>{OUT[i.outcome]?.[0] ?? i.outcome}</Pill>{i.leaked_sensitive_data && <span className="tag bad" style={{ marginLeft: 6 }}>Leak</span>}</td>
                  <td className="r muted">{ms(i.latency_ms)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </div>
      </Card>

      <Drawer open={!!sel} onClose={() => setSel(null)} title={sel ? OUT[sel.outcome]?.[0] ?? "Prompt" : ""} sub={sel ? `${sel.harmful ? "Attack" : "Benign"}${sel.category ? ` · ${humanize(sel.category)}` : ""}${sel.strategy ? ` · ${humanize(sel.strategy)}` : ""}` : undefined}>
        {sel && (
          <div className="stack">
            <section><h3 className="small strong" style={{ margin: "0 0 6px" }}>Prompt sent</h3><div className="code">{sel.prompt}</div></section>
            <section><h3 className="small strong" style={{ margin: "0 0 6px" }}>Agent response</h3><div className="code">{sel.response || <span className="muted">No response</span>}</div></section>
            <dl className="kv">
              <dt>Outcome</dt><dd><Pill tone={OUT[sel.outcome]?.[2]} dot>{OUT[sel.outcome]?.[0]}</Pill></dd>
              {sel.classification && <><dt>Grading</dt><dd>{sel.classification}</dd></>}
              <dt>Latency</dt><dd>{ms(sel.latency_ms)}</dd>
              {sel.status_code != null && <><dt>HTTP status</dt><dd>{sel.status_code}</dd></>}
              {sel.leaked_sensitive_data && <><dt>Data leak</dt><dd style={{ color: "var(--danger)" }}>Sensitive data detected in the response</dd></>}
              {sel.error && <><dt>Error</dt><dd>{sel.error}</dd></>}
            </dl>
          </div>
        )}
      </Drawer>
    </>
  );
}
