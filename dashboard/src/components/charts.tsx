"use client";
/**
 * Lightweight SVG charts in the Evergreen style: thin marks, rounded data ends,
 * recessive grid, value labels where few, hover tooltips everywhere.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";

// ─── helpers ────────────────────────────────────────────────────────────

export const SERIES = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)"];
export const SEQ = ["var(--s1)", "var(--s2)", "var(--s3)"];

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      setSize((s) => (Math.abs(s.w - width) < 1 && Math.abs(s.h - height) < 1 ? s : { w: width, h: height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

export function niceMax(max: number, ticks = 4): { max: number; step: number } {
  if (!(max > 0)) return { max: 1, step: 0.25 };
  const raw = max / ticks;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const f = raw / mag;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
  return { max: step * Math.ceil(max / step - 1e-9), step };
}

function every(n: number, width: number, min = 56) {
  return Math.max(1, Math.ceil(n / Math.max(2, Math.floor(width / min))));
}

const roundTop = (x: number, y: number, w: number, base: number, r: number) => {
  const rr = Math.min(r, w / 2, Math.max(0, base - y));
  return `M${x} ${base}V${y + rr}Q${x} ${y} ${x + rr} ${y}H${x + w - rr}Q${x + w} ${y} ${x + w} ${y + rr}V${base}Z`;
};

function smooth(pts: [number, number][]) {
  if (!pts.length) return "";
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], mx = (x0 + x1) / 2;
    d += ` C${mx} ${y0} ${mx} ${y1} ${x1} ${y1}`;
  }
  return d;
}

type TipRow = { name: string; value: string; color?: string };
type TipState = { x: number; y: number; title: string; rows: TipRow[] } | null;

function Tip({ tip, width }: { tip: TipState; width: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useEffect(() => {
    if (!tip || !ref.current) return;
    const w = ref.current.offsetWidth, h = ref.current.offsetHeight;
    setPos({ left: Math.max(0, Math.min(tip.x - w / 2, width - w)), top: Math.max(-6, tip.y - h - 12) });
  }, [tip, width]);
  if (!tip) return null;
  return (
    <div className="tip" ref={ref} style={{ left: pos?.left ?? -9999, top: pos?.top ?? 0 }}>
      <b>{tip.title}</b>
      {tip.rows.map((r, i) => (
        <div className="tr-row" key={i}><span>{r.color && <i style={{ background: r.color }} />}{r.name}</span><span>{r.value}</span></div>
      ))}
    </div>
  );
}

// ─── Bar chart (single series) ──────────────────────────────────────────

export interface BarDatum { label: string; long?: string; value: number; extra?: TipRow[] }

export function BarChart({ data, fmt, fmtAxis, height = 220, emphasis = "last", valueLabels = true, ariaLabel }: {
  data: BarDatum[]; fmt: (v: number) => string; fmtAxis: (v: number) => string; height?: number | "fill";
  emphasis?: "last" | "max" | "none"; valueLabels?: boolean; ariaLabel: string;
}) {
  const [ref, { w, h }] = useSize<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);
  const H = height === "fill" ? h : height;
  const n = data.length;
  const m = { l: 46, r: 6, t: 20, b: 22 };
  const pw = Math.max(0, w - m.l - m.r), ph = Math.max(0, H - m.t - m.b);
  const { max, step } = niceMax(Math.max(...data.map((d) => d.value), 0));
  const y = (v: number) => m.t + ph - (v / max) * ph;
  const band = n ? pw / n : 0, bw = Math.min(44, Math.max(3, band * (n > 40 ? 0.7 : 0.46)));
  const peak = data.reduce((bi, d, i) => (d.value > data[bi].value ? i : bi), 0);
  const showVals = valueLabels && n <= 16 && band > 34;
  const skip = every(n, pw);
  const ticks: number[] = [];
  for (let v = 0; v <= max + 1e-12; v += step) ticks.push(v);

  return (
    <div className="chart" ref={ref} style={{ height: height === "fill" ? "100%" : H, minHeight: height === "fill" ? 180 : undefined }}>
      {w > 0 && H > 0 && (
        <svg width={w} height={H} viewBox={`0 0 ${w} ${H}`} role="img" aria-label={ariaLabel}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={m.l} x2={w - m.r} y1={Math.round(y(v)) + 0.5} y2={Math.round(y(v)) + 0.5} className={v ? "gl" : "bl"} />
              <text x={m.l - 10} y={y(v) + 3.5} textAnchor="end" className="ax">{fmtAxis(v)}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = m.l + band * i + band / 2, x0 = cx - bw / 2, on = d.value > 0;
            const strong = emphasis === "last" ? i === n - 1 : emphasis === "max" ? i === peak : false;
            return (
              <g key={i} className="hov" tabIndex={0} aria-label={`${d.long ?? d.label}: ${fmt(d.value)}`}
                onMouseEnter={() => setTip({ x: cx, y: on ? y(d.value) : y(0) - 10, title: d.long ?? d.label, rows: [{ name: "Value", value: fmt(d.value) }, ...(d.extra ?? [])] })}
                onFocus={() => setTip({ x: cx, y: on ? y(d.value) : y(0) - 10, title: d.long ?? d.label, rows: [{ name: "Value", value: fmt(d.value) }, ...(d.extra ?? [])] })}
                onMouseLeave={() => setTip(null)} onBlur={() => setTip(null)}>
                <rect className="hcol" x={cx - band / 2 + 2} y={m.t - 12} width={Math.max(0, band - 4)} height={ph + 12} rx={8} />
                {on
                  ? <path d={roundTop(x0, y(d.value), bw, y(0), 4)} fill={strong ? "var(--accent)" : "var(--s2)"} />
                  : <rect x={x0} y={y(0) - 2} width={bw} height={2} rx={1} fill="var(--line-2)" />}
                {showVals && <text x={cx} y={on ? Math.max(10, y(d.value) - 7) : y(0) - 8} textAnchor="middle" className={on ? "vl" : "ax"}>{on ? fmt(d.value) : fmtAxis(0)}</text>}
                {((i % skip === 0 && (i === n - 1 || n - 1 - i >= skip)) || i === n - 1) && <text x={cx} y={H - 5} textAnchor="middle" className={`ax${on && n <= 16 ? " ax-on" : ""}`}>{d.label}</text>}
              </g>
            );
          })}
        </svg>
      )}
      <Tip tip={tip} width={w} />
    </div>
  );
}

// ─── Stacked bars ───────────────────────────────────────────────────────

export interface Series { name: string; color: string; values: number[] }

export function StackedBars({ labels, longs, series, fmt, fmtAxis, height = 240, ariaLabel }: {
  labels: string[]; longs?: string[]; series: Series[]; fmt: (v: number) => string; fmtAxis: (v: number) => string; height?: number | "fill"; ariaLabel: string;
}) {
  const [ref, { w, h }] = useSize<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);
  const H = height === "fill" ? h : height;
  const n = labels.length;
  const m = { l: 46, r: 6, t: 12, b: 22 };
  const pw = Math.max(0, w - m.l - m.r), ph = Math.max(0, H - m.t - m.b);
  const totals = labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
  const { max, step } = niceMax(Math.max(...totals, 0));
  const y = (v: number) => m.t + ph - (v / max) * ph;
  const band = n ? pw / n : 0, bw = Math.min(40, Math.max(3, band * (n > 40 ? 0.72 : 0.5)));
  const skip = every(n, pw);
  const ticks: number[] = [];
  for (let v = 0; v <= max + 1e-12; v += step) ticks.push(v);
  return (
    <div className="chart" ref={ref} style={{ height: height === "fill" ? "100%" : H, minHeight: height === "fill" ? 180 : undefined }}>
      {w > 0 && H > 0 && (
        <svg width={w} height={H} viewBox={`0 0 ${w} ${H}`} role="img" aria-label={ariaLabel}>
          <defs>
            {labels.map((_, i) => {
              const cx = m.l + band * i + band / 2;
              return <clipPath key={i} id={`sb-${ariaLabel.length}-${i}`}><path d={roundTop(cx - bw / 2, y(totals[i]), bw, y(0), 4)} /></clipPath>;
            })}
          </defs>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={m.l} x2={w - m.r} y1={Math.round(y(v)) + 0.5} y2={Math.round(y(v)) + 0.5} className={v ? "gl" : "bl"} />
              <text x={m.l - 10} y={y(v) + 3.5} textAnchor="end" className="ax">{fmtAxis(v)}</text>
            </g>
          ))}
          {labels.map((lab, i) => {
            const cx = m.l + band * i + band / 2, x0 = cx - bw / 2;
            let acc = 0;
            const rows = series.map((s) => ({ name: s.name, value: fmt(s.values[i] || 0), color: s.color, raw: s.values[i] || 0 }))
              .filter((r) => r.raw > 0).sort((a, b) => b.raw - a.raw);
            const show = () => setTip({ x: cx, y: y(totals[i]), title: longs?.[i] ?? lab, rows: [...rows, { name: "Total", value: fmt(totals[i]) }] });
            return (
              <g key={i} className="hov" tabIndex={0} onMouseEnter={show} onFocus={show} onMouseLeave={() => setTip(null)} onBlur={() => setTip(null)} aria-label={`${longs?.[i] ?? lab}: ${fmt(totals[i])}`}>
                <rect className="hcol" x={cx - band / 2 + 2} y={m.t} width={Math.max(0, band - 4)} height={ph} rx={8} />
                {totals[i] > 0 ? (
                  <g clipPath={`url(#sb-${ariaLabel.length}-${i})`}>
                    {series.map((s, k) => {
                      const v = s.values[i] || 0;
                      if (!v) return null;
                      const y1 = y(acc + v), y0 = y(acc);
                      acc += v;
                      return <g key={k}><rect x={x0} y={y1} width={bw} height={Math.max(0, y0 - y1)} fill={s.color} />{acc - v > 0 && <rect x={x0} y={y0 - 0.75} width={bw} height={1.5} fill="var(--panel)" />}</g>;
                    })}
                  </g>
                ) : <rect x={x0} y={y(0) - 2} width={bw} height={2} rx={1} fill="var(--line-2)" />}
                {((i % skip === 0 && (i === n - 1 || n - 1 - i >= skip)) || i === n - 1) && <text x={cx} y={H - 5} textAnchor="middle" className="ax">{lab}</text>}
              </g>
            );
          })}
        </svg>
      )}
      <Tip tip={tip} width={w} />
    </div>
  );
}

// ─── Line chart ─────────────────────────────────────────────────────────

export function LineChart({ labels, longs, series, fmt, fmtAxis, height = 200, area = true, ariaLabel }: {
  labels: string[]; longs?: string[]; series: Series[]; fmt: (v: number) => string; fmtAxis: (v: number) => string; height?: number | "fill"; area?: boolean; ariaLabel: string;
}) {
  const [ref, { w, h }] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = height === "fill" ? h : height;
  const n = labels.length;
  const m = { l: 42, r: 8, t: 10, b: 22 };
  const pw = Math.max(0, w - m.l - m.r), ph = Math.max(0, H - m.t - m.b);
  const { max, step } = niceMax(Math.max(0, ...series.flatMap((s) => s.values)) * 1.08);
  const x = (i: number) => m.l + (n <= 1 ? pw / 2 : (i / (n - 1)) * pw);
  const y = (v: number) => m.t + ph - (v / max) * ph;
  const skip = every(n, pw, 64);
  const ticks: number[] = [];
  for (let v = 0; v <= max + 1e-12; v += step) ticks.push(v);
  const tip: TipState = hover == null ? null : {
    x: x(hover), y: m.t + ph / 2, title: longs?.[hover] ?? labels[hover],
    rows: series.map((s) => ({ name: s.name, value: fmt(s.values[hover] || 0), color: s.color })),
  };
  return (
    <div className="chart" ref={ref} style={{ height: height === "fill" ? "100%" : H, minHeight: height === "fill" ? 150 : undefined }}>
      {w > 0 && H > 0 && (
        <svg width={w} height={H} viewBox={`0 0 ${w} ${H}`} role="img" aria-label={ariaLabel}
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const px = e.clientX - r.left;
            setHover(Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / (pw || 1)) * (n - 1)))));
          }}
          onMouseLeave={() => setHover(null)}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={m.l} x2={w - m.r} y1={Math.round(y(v)) + 0.5} y2={Math.round(y(v)) + 0.5} className={v ? "gl" : "bl"} />
              <text x={m.l - 8} y={y(v) + 3.5} textAnchor="end" className="ax">{fmtAxis(v)}</text>
            </g>
          ))}
          {labels.map((l, i) => ((i % skip === 0 && (i === n - 1 || n - 1 - i >= skip)) || i === n - 1) && (
            <text key={i} x={x(i)} y={H - 5} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"} className="ax">{l}</text>
          ))}
          {area && series[0] && n > 1 && (
            <path d={`${smooth(series[0].values.map((v, i) => [x(i), y(v)]))} L${x(n - 1)} ${y(0)} L${x(0)} ${y(0)} Z`} fill="var(--fill)" />
          )}
          {[...series].reverse().map((s) => (
            n > 1
              ? <path key={s.name} d={smooth(s.values.map((v, i) => [x(i), y(v)]))} fill="none" stroke={s.color} strokeWidth={1.75} strokeLinecap="round" />
              : <circle key={s.name} cx={x(0)} cy={y(s.values[0] || 0)} r={3.5} fill={s.color} />
          ))}
          {hover != null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={m.t} y2={m.t + ph} stroke="var(--line-2)" />
              {series.map((s) => <circle key={s.name} cx={x(hover)} cy={y(s.values[hover] || 0)} r={3.5} fill={s.color} stroke="var(--panel)" strokeWidth={2} />)}
            </g>
          )}
        </svg>
      )}
      <Tip tip={tip} width={w} />
    </div>
  );
}

// ─── Ring (donut) ───────────────────────────────────────────────────────

export interface Slice { name: string; value: number; color: string }

export function Ring({ slices, size = 72, stroke = 8, center, active, onActive, ariaLabel }: {
  slices: Slice[]; size?: number; stroke?: number; center?: ReactNode; active?: number | null; onActive?: (i: number | null) => void; ariaLabel: string;
}) {
  const total = slices.reduce((a, s) => a + s.value, 0);
  const R = size / 2 - stroke / 2 - 1, C = 2 * Math.PI * R, GAP = slices.filter((s) => s.value > 0).length > 1 ? 2 : 0;
  let off = 0;
  return (
    <div className={`ring${active != null ? " dim" : ""}`} style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={ariaLabel}>
        <circle cx={size / 2} cy={size / 2} r={R} fill="none" stroke="var(--hover)" strokeWidth={stroke} />
        {total > 0 && slices.map((s, i) => {
          const frac = s.value / total;
          const len = Math.max(frac > 0 ? 1.5 : 0, frac * C - GAP);
          const el = (
            <circle key={i} className={`seg${active === i ? " on" : ""}`} cx={size / 2} cy={size / 2} r={R} fill="none" stroke={s.color} strokeWidth={stroke}
              strokeDasharray={`${len} ${C}`} strokeDashoffset={-off} transform={`rotate(-90 ${size / 2} ${size / 2})`}
              onMouseEnter={() => onActive?.(i)} onMouseLeave={() => onActive?.(null)} />
          );
          off += frac * C;
          return el;
        })}
      </svg>
      {center && <div className="ctr">{center}</div>}
    </div>
  );
}

// ─── Mini visuals for KPI cards ─────────────────────────────────────────

export function MiniBars({ values, width = 64, height = 28 }: { values: number[]; width?: number; height?: number }) {
  const n = Math.max(values.length, 1), bw = Math.min(6, width / n - 2), gap = n > 1 ? (width - bw * n) / (n - 1) : 0;
  const mx = Math.max(...values, 0);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {values.map((v, i) => {
        const hh = v > 0 && mx > 0 ? Math.max(4, (v / mx) * height) : 2;
        return <rect key={i} x={i * (bw + gap)} y={height - hh} width={bw} height={hh} rx={1.5} fill={v > 0 ? (i === n - 1 ? "var(--accent)" : "var(--accent-line)") : "var(--line-2)"} />;
      })}
    </svg>
  );
}

export function Sparkline({ values, width = 72, height = 28, color = "var(--accent)" }: { values: number[]; width?: number; height?: number; color?: string }) {
  if (values.length < 2) return <MiniBars values={values} width={width} height={height} />;
  const mx = Math.max(...values), mn = Math.min(...values);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * width, height - 3 - ((v - mn) / (mx - mn || 1)) * (height - 8)] as [number, number]);
  const d = smooth(pts);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={`${d} L${width} ${height} L0 ${height} Z`} fill="var(--fill)" />
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinecap="round" />
    </svg>
  );
}

export function SplitBar({ parts, width = 64 }: { parts: { value: number; color: string }[]; width?: number }) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  return (
    <svg width={width} height={28} viewBox={`0 0 ${width} 28`}>
      <rect x={0} y={16} width={width} height={10} rx={2.5} fill="var(--hover)" />
      {total > 0 && (() => {
        let x = 0;
        return parts.map((p, i) => {
          const w = (p.value / total) * width;
          const r = <rect key={i} x={x} y={16} width={Math.max(p.value > 0 ? 2 : 0, w - (i < parts.length - 1 ? 2 : 0))} height={10} rx={2.5} fill={p.color} />;
          x += w;
          return r;
        });
      })()}
    </svg>
  );
}

export function CheckRing({ ok = true, size = 28 }: { ok?: boolean; size?: number }) {
  const c = ok ? "var(--accent)" : "var(--danger)";
  return (
    <svg width={size} height={size} viewBox="0 0 28 28">
      <circle cx={14} cy={14} r={11} fill="none" stroke={c} strokeWidth={3.5} />
      {ok ? <path d="M9.5 14.2l3 3 6-6.2" fill="none" stroke={c} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        : <path d="M10 10l8 8M18 10l-8 8" fill="none" stroke={c} strokeWidth={2} strokeLinecap="round" />}
    </svg>
  );
}

export function ShareBar({ slices, active }: { slices: Slice[]; active?: number | null }) {
  const total = slices.reduce((a, s) => a + s.value, 0) || 1;
  return (
    <div className="sharebar" aria-hidden>
      {slices.map((s, i) => (
        <i key={i} style={{ flex: `${Math.round((s.value / total) * 1e6)} 1 0`, background: s.color, opacity: active != null && active !== i ? 0.25 : 1 }} />
      ))}
    </div>
  );
}
