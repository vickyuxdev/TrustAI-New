"use client";
/** Shared UI primitives for the TrustAI dashboard (Evergreen design system). */
import {
  createContext, useCallback, useContext, useEffect, useId, useRef, useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  ArrowDownRight, ArrowRight, ArrowUpRight, Check, ChevronDown, Copy, Inbox, RefreshCw, TriangleAlert, X,
  type LucideIcon,
} from "lucide-react";

// ─── Layout ─────────────────────────────────────────────────────────────

export function PageHead({ kicker, title, sub, actions }: { kicker?: ReactNode; title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="grow">
        {kicker && <div className="kicker">{kicker}</div>}
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {actions && <div className="head-r">{actions}</div>}
    </div>
  );
}

export function Card({ children, className = "", style, id, labelledBy }: { children: ReactNode; className?: string; style?: React.CSSProperties; id?: string; labelledBy?: string }) {
  return <section className={`card ${className}`} style={style} id={id} aria-labelledby={labelledBy}>{children}</section>;
}

export function CardHeader({ title, sub, action, bordered, id }: { title: ReactNode; sub?: ReactNode; action?: ReactNode; bordered?: boolean; id?: string }) {
  return (
    <div className={`card-h${bordered ? " bordered" : ""}`}>
      <div className="grow">
        <h2 className="card-t" id={id}>{title}</h2>
        {sub && <div className="card-s">{sub}</div>}
      </div>
      {action}
    </div>
  );
}

export function MoreLink({ href, children }: { href: string; children: ReactNode }) {
  return <Link className="link" href={href}>{children}<ArrowRight className="ic" aria-hidden /></Link>;
}

// ─── KPI ────────────────────────────────────────────────────────────────

export function Kpi({ icon: Icon, label, value, foot, vis, link, tone }: {
  icon: LucideIcon; label: string; value: ReactNode; foot?: ReactNode; vis?: ReactNode;
  link?: { href: string; label: string }; tone?: "bad" | "wait";
}) {
  return (
    <article className="kpi" aria-label={label}>
      <div className="k">
        <span className={`ki${tone ? " " + tone : ""}`}><Icon className="ic" aria-hidden /></span>
        {label}
        {link && <Link className="lk" href={link.href}>{link.label}<ArrowRight className="ic" style={{ width: 12, height: 12 }} aria-hidden /></Link>}
      </div>
      <div className="vrow">
        <div className="v">{value}</div>
        {vis && <div className="vis" aria-hidden>{vis}</div>}
      </div>
      {foot && <div className="f">{foot}</div>}
    </article>
  );
}

export function Duo({ a, b }: { a: [ReactNode, ReactNode]; b: [ReactNode, ReactNode] }) {
  return (
    <div className="duo">
      <div><b>{a[0]}</b><span>{a[1]}</span></div>
      <span className="sep" aria-hidden />
      <div><b>{b[0]}</b><span>{b[1]}</span></div>
    </div>
  );
}

// ─── Small atoms ────────────────────────────────────────────────────────

export type Tone = "accent" | "wait" | "danger" | "blue" | undefined;
export function Pill({ tone, dot, icon: Icon, children, title }: { tone?: Tone; dot?: boolean; icon?: LucideIcon; children: ReactNode; title?: string }) {
  return (
    <span className={`pill${tone ? " pill-" + tone : ""}`} title={title}>
      {dot && <span className="dot" aria-hidden />}
      {Icon && <Icon className="ic" aria-hidden />}
      {children}
    </span>
  );
}

export function Tag({ tone, children }: { tone?: "ok" | "bad" | "wait"; children: ReactNode }) {
  return <span className={`tag${tone ? " " + tone : ""}`}>{children}</span>;
}

/** Change vs previous period. `better` decides colour: "down" means a decrease is good. */
export function Delta({ pct, better = "none" }: { pct: number | null | undefined; better?: "up" | "down" | "none" }) {
  if (pct == null || Math.abs(pct) < 0.05) return <span className="delta flat">0%</span>;
  const up = pct > 0;
  const cls = better === "none" ? "flat" : up === (better === "up") ? "good" : "bad";
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return <span className={`delta ${cls}`}><Icon className="ic" aria-hidden />{up ? "+" : "−"}{Math.abs(pct).toFixed(1)}%</span>;
}

export function StatusDot({ tone, children }: { tone: "ok" | "bad" | "wait" | "idle"; children: ReactNode }) {
  return <span className={`sdot ${tone}`}><i aria-hidden />{children}</span>;
}

export function ColorChip({ color, children }: { color: string; children: ReactNode }) {
  return <span className="chip"><i style={{ background: color }} aria-hidden /><span className="ellipsis">{children}</span></span>;
}

export function StatStrip({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <div className="stat-strip" style={{ ["--n" as string]: items.length } as React.CSSProperties}>
      {items.map(([k, v], i) => <div key={i}><span>{k}</span><b>{v}</b></div>)}
    </div>
  );
}

export function ShareCell({ fraction, color, label }: { fraction: number; color?: string; label?: string }) {
  return (
    <span className="share">
      <span className="tr" aria-hidden><i style={{ width: `${Math.max(0, Math.min(1, fraction)) * 100}%`, background: color }} /></span>
      {label}
    </span>
  );
}

// ─── Controls ───────────────────────────────────────────────────────────

export function Seg<T extends string>({ value, onChange, options, label, small }: {
  value: T; onChange: (v: T) => void; options: readonly (readonly [T, ReactNode])[]; label: string; small?: boolean;
}) {
  return (
    <div className={`seg${small ? " sm" : ""}`} role="group" aria-label={label}>
      {options.map(([v, l]) => <button key={v} type="button" aria-pressed={v === value} onClick={() => onChange(v)}>{l}</button>)}
    </div>
  );
}

export function ChipSelect({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
}) {
  const id = useId();
  return (
    <label className="chip-select" htmlFor={id}>
      <span>{label}</span>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <ChevronDown className="ic" aria-hidden />
    </label>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs, label }: {
  value: T; onChange: (v: T) => void; tabs: readonly { id: T; label: ReactNode; count?: number | null }[]; label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}>
          {t.label}{t.count != null && <span className="tc">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="btn btn-sm" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ }
    }}>
      {done ? <Check className="ic" aria-hidden /> : <Copy className="ic" aria-hidden />}{done ? "Copied" : label}
    </button>
  );
}

// ─── States ─────────────────────────────────────────────────────────────

export function Empty({ icon: Icon = Inbox, title, children, action }: { icon?: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="ei"><Icon className="ic" aria-hidden /></span>
      <b>{title}</b>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const e = error as { message?: string; unreachable?: boolean } | null;
  const title = e?.unreachable ? "Service unreachable" : "Couldn't load this";
  const msg = e?.unreachable
    ? "The TrustAI service behind this view isn't responding. Check that it's running, then try again."
    : e?.message || "Something went wrong.";
  if (compact) {
    return (
      <div className="banner bad" role="alert">
        <TriangleAlert className="ic" aria-hidden />
        <span className="grow"><b>{title}.</b> {msg}</span>
        {onRetry && <button type="button" className="btn btn-sm" onClick={onRetry}><RefreshCw className="ic" aria-hidden />Retry</button>}
      </div>
    );
  }
  return (
    <div className="empty" role="alert">
      <span className="ei" style={{ color: "var(--danger)", background: "var(--danger-soft)", borderColor: "var(--danger-line)" }}><TriangleAlert className="ic" aria-hidden /></span>
      <b>{title}</b>
      <p>{msg}</p>
      {onRetry && <button type="button" className="btn btn-sm" onClick={onRetry}><RefreshCw className="ic" aria-hidden />Try again</button>}
    </div>
  );
}

export function Skel({ w = "100%", h = 14, r }: { w?: number | string; h?: number; r?: number }) {
  return <span className="skel" style={{ display: "block", width: w, height: h, borderRadius: r }} aria-hidden />;
}
export function SkelRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="stack-sm" style={{ padding: "14px 18px" }} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skel key={i} h={18} w={`${92 - (i % 3) * 14}%`} />)}
    </div>
  );
}

// ─── Overlays ───────────────────────────────────────────────────────────

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [open, onClose]);
}

export function Modal({ open, onClose, title, sub, children, footer, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; sub?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEscape(open, onClose);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) ref.current?.querySelector<HTMLElement>("input,select,textarea,button:not(.icon-btn)")?.focus(); }, [open]);
  if (!open) return null;
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} ref={ref}>
        <div className="modal-h">
          <div><h2>{title}</h2>{sub && <p>{sub}</p>}</div>
          <button type="button" className="icon-btn sm" onClick={onClose} aria-label="Close"><X className="ic" /></button>
        </div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, sub, children, actions, wide, lead }: {
  open: boolean; onClose: () => void; title: ReactNode; sub?: ReactNode; children: ReactNode; actions?: ReactNode; wide?: boolean; lead?: ReactNode;
}) {
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <>
      <div className="drawer-wrap" onClick={onClose} aria-hidden />
      <aside className={`drawer${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : "Details"}>
        <div className="drawer-h">
          {lead}
          <div className="grow"><h2 className="card-t" style={{ fontSize: 15 }}>{title}</h2>{sub && <div className="card-s">{sub}</div>}</div>
          {actions}
          <button type="button" className="icon-btn sm" onClick={onClose} aria-label="Close"><X className="ic" /></button>
        </div>
        <div className="drawer-b">{children}</div>
      </aside>
    </>
  );
}

// ─── Toasts ─────────────────────────────────────────────────────────────

type ToastItem = { id: number; text: string; bad?: boolean };
const ToastCtx = createContext<(text: string, bad?: boolean) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, bad?: boolean) => {
    const id = Date.now() + Math.random();
    setItems((l) => [...l, { id, text, bad }]);
    setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), 3800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast${t.bad ? " bad" : ""}`}>{t.bad ? <TriangleAlert className="ic" aria-hidden /> : <Check className="ic" aria-hidden />}{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/** Message from any thrown API/governance error. */
export function errMsg(e: unknown): string {
  return (e as { message?: string } | null)?.message || "Something went wrong";
}
