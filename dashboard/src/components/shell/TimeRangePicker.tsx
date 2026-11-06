"use client";
import { useEffect, useRef, useState } from "react";
import { Calendar, Check, ChevronDown } from "lucide-react";
import { useTimeRange } from "@/lib/useTimeRange";
import { PRESETS, describeBounds, describeTimeRange, resolveTimeRange, toLocalInputValue, validateCustomRange } from "@/lib/timeRange";

export function TimeRangePicker() {
  const { spec, setSpec } = useTimeRange();
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const openMenu = () => {
    const r = resolveTimeRange(spec);
    setFrom(toLocalInputValue(r.from)); setTo(toLocalInputValue(r.to)); setErr(null); setCustom(spec.kind === "custom"); setOpen((o) => !o);
  };

  return (
    <div style={{ position: "relative" }} ref={ref}>
      <button type="button" className="btn" onClick={openMenu} aria-haspopup="menu" aria-expanded={open} title={describeBounds(spec)}>
        <Calendar className="ic" aria-hidden />{describeTimeRange(spec)}<ChevronDown className="ic" aria-hidden />
      </button>
      {open && (
        <div className="menu" role="menu" style={{ right: 0, top: 38, width: 260 }}>
          {PRESETS.map((p) => (
            <button key={p.key} type="button" role="menuitemradio" aria-checked={spec.kind === "preset" && spec.preset === p.key}
              onClick={() => { setSpec({ kind: "preset", preset: p.key }); setOpen(false); }}>
              {p.label}{spec.kind === "preset" && spec.preset === p.key && <Check className="ic" style={{ color: "var(--accent)" }} aria-hidden />}
            </button>
          ))}
          <div className="sep" />
          <button type="button" role="menuitemradio" aria-checked={spec.kind === "custom"} onClick={() => setCustom((c) => !c)}>
            Custom range<ChevronDown className="ic" aria-hidden style={{ transform: custom ? "rotate(180deg)" : undefined }} />
          </button>
          {custom && (
            <div className="stack-sm" style={{ padding: "6px 8px 8px" }}>
              <div className="field"><label htmlFor="tr-from">From</label><input id="tr-from" className="input" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
              <div className="field"><label htmlFor="tr-to">To</label><input id="tr-to" className="input" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></div>
              {err && <div className="small" style={{ color: "var(--danger)" }}>{err}</div>}
              <button type="button" className="btn btn-primary btn-sm" style={{ justifyContent: "center" }} onClick={() => {
                const v = validateCustomRange(from, to);
                if (!v.ok) { setErr(v.error); return; }
                setSpec(v.spec); setOpen(false);
              }}>Apply range</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
