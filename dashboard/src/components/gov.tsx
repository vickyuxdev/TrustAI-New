"use client";
/** Governance-specific badges and small composites. */
import Link from "next/link";
import { Pill, type Tone } from "@/components/ui";
import { LIFECYCLE_STATUSES, type Agent, type Decision, type EvaluationStatus, type LifecycleStatus, type AssessmentStatus } from "@/lib/governance";

const LIFE_TONE: Record<LifecycleStatus, Tone> = {
  registered: undefined, onboarded: undefined, assessed: "blue", evaluated: "blue",
  approved: "accent", deployed: "accent", suspended: "danger", retired: undefined,
};
export const LIFE_LABEL: Record<LifecycleStatus, string> = {
  registered: "Registered", onboarded: "Onboarded", assessed: "Assessed", evaluated: "Evaluated",
  approved: "Approved", deployed: "Deployed", suspended: "Suspended", retired: "Retired",
};
export function LifecycleBadge({ status }: { status: LifecycleStatus }) {
  return <Pill tone={LIFE_TONE[status]} dot>{LIFE_LABEL[status] ?? status}</Pill>;
}

export const TIER_LABEL: Record<number, string> = { 1: "Minimal", 2: "Limited", 3: "High", 4: "Critical" };
export function TierBadge({ tier }: { tier: number | null | undefined }) {
  if (tier == null) return <Pill>Not assessed</Pill>;
  const tone: Tone = tier >= 4 ? "danger" : tier === 3 ? "wait" : tier === 2 ? "blue" : "accent";
  return <Pill tone={tone}>Tier {tier} · {TIER_LABEL[tier]}</Pill>;
}

/** Trust score 0–100 with a small meter; ≥ 95 meets the default release threshold. */
export function TrustScore({ score, threshold = 95, compact }: { score: number | null | undefined; threshold?: number; compact?: boolean }) {
  if (score == null) return <span className="muted">No score</span>;
  const ok = score >= threshold;
  const color = ok ? "var(--accent)" : score >= threshold - 10 ? "var(--wait)" : "var(--danger)";
  return (
    <span className="meter" style={{ minWidth: compact ? 90 : 140 }} title={`Release threshold ${threshold}`}>
      <b className="num" style={{ color: ok ? "var(--accent-text)" : color, minWidth: 34 }}>{score.toFixed(1)}</b>
      <span className="bar-track" aria-hidden><i style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: color }} /></span>
    </span>
  );
}

export function DecisionBadge({ decision }: { decision: Decision | null }) {
  if (!decision) return <Pill tone="wait" dot>Awaiting decision</Pill>;
  if (decision === "approved") return <Pill tone="accent" dot>Approved</Pill>;
  if (decision === "approved_with_conditions") return <Pill tone="accent" dot>Approved with conditions</Pill>;
  return <Pill tone="danger" dot>Rejected</Pill>;
}

const ASSESS_LABEL: Record<AssessmentStatus, [string, Tone]> = {
  draft: ["Draft", undefined], submitted: ["Submitted", "blue"], classified: ["Needs decision", "wait"], decided: ["Decided", "accent"],
};
export function AssessmentBadge({ status }: { status: AssessmentStatus }) {
  const [l, t] = ASSESS_LABEL[status] ?? [status, undefined];
  return <Pill tone={t} dot>{l}</Pill>;
}

const EVAL_TONE: Record<EvaluationStatus, Tone> = { queued: "blue", running: "blue", completed: "accent", failed: "danger", cancelled: undefined };
export function EvalBadge({ status, progress, total }: { status: EvaluationStatus; progress?: number; total?: number }) {
  const live = status === "running" || status === "queued";
  return (
    <span className={`pill pill-${EVAL_TONE[status] ?? ""}`}>
      {live ? <span className="live" aria-hidden style={{ background: "var(--c2)" }} /> : <span className="dot" aria-hidden />}
      {status === "running" && progress != null && total ? `Running · ${Math.round((progress / total) * 100)}%` : status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase();
  const tone: Tone = s === "critical" || s === "high" || s === "error" ? "danger" : s === "warning" || s === "medium" ? "wait" : undefined;
  return <Pill tone={tone} dot>{severity}</Pill>;
}

export function AgentLink({ agent, id }: { agent?: Agent; id: string | null }) {
  if (!id) return <span className="muted">—</span>;
  return <Link href={`/governance/agents/${id}`} className="strong" style={{ color: "var(--text)" }}>{agent?.name ?? `${id.slice(0, 8)}…`}</Link>;
}

/** Lifecycle as a horizontal stepper (suspended/retired shown as a pill instead). */
export function LifecycleSteps({ status }: { status: LifecycleStatus }) {
  const path = LIFECYCLE_STATUSES.filter((s) => s !== "suspended" && s !== "retired");
  const idx = path.indexOf(status as (typeof path)[number]);
  return (
    <ol className="steps" aria-label="Lifecycle">
      {path.map((s, i) => (
        <li key={s} className={idx > i ? "done" : idx === i ? "cur" : ""}><span className="n">{idx > i ? "✓" : i + 1}</span>{LIFE_LABEL[s]}</li>
      ))}
    </ol>
  );
}
