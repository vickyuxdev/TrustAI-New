"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import {
  Bell, Bot, Building2, ChevronDown, CircleHelp, ClipboardCheck, Coins, DollarSign, FolderKanban, GitBranch, History, KeyRound,
  LayoutGrid, Library, Network, PanelLeft, Plug, ScrollText, ShieldCheck, Swords, type LucideIcon,
} from "lucide-react";
import { useActiveAlertCount } from "@/lib/api";
import { RANGE_PARAMS } from "@/lib/timeRange";

type Item = { label: string; href: string; icon: LucideIcon; exact?: boolean; badge?: "alerts"; live?: boolean };
const GROUPS: { id: string; label: string; items: Item[] }[] = [
  { id: "observe", label: "Observability", items: [
    { label: "Dashboard", href: "/", icon: LayoutGrid, exact: true },
    { label: "Projects", href: "/projects", icon: FolderKanban },
    { label: "Agents", href: "/agents", icon: Bot },
    { label: "Traces", href: "/traces", icon: GitBranch, live: true },
    { label: "Clients", href: "/clients", icon: Building2 },
    { label: "Cost Insights", href: "/cost", icon: DollarSign },
  ] },
  { id: "gov", label: "Governance", items: [
    { label: "Overview", href: "/governance", icon: ShieldCheck, exact: true },
    { label: "Agent Registry", href: "/governance/agents", icon: Library },
    { label: "Risk Assessments", href: "/governance/risk", icon: ClipboardCheck },
    { label: "Policies & Guardrails", href: "/governance/policies", icon: ScrollText },
    { label: "Red-Team", href: "/governance/evaluations", icon: Swords },
    { label: "AI Gateway", href: "/governance/gateway", icon: Network },
    { label: "Audit Events", href: "/governance/events", icon: History },
  ] },
  { id: "settings", label: "Settings", items: [
    { label: "Alerts", href: "/alerts", icon: Bell, badge: "alerts" },
    { label: "Connectors", href: "/settings/connectors", icon: Plug },
    { label: "SDK & API Keys", href: "/settings/onboarding", icon: KeyRound },
    { label: "Model Pricing", href: "/settings/pricing", icon: Coins },
  ] },
];

export function Sidebar({ onToggle }: { onToggle: () => void }) {
  const path = usePathname();
  const params = useSearchParams();
  const alerts = useActiveAlertCount();
  const [closed, setClosed] = useState<Record<string, boolean>>({});

  // Keep the selected time range when moving between pages.
  const carry = new URLSearchParams();
  RANGE_PARAMS.forEach((k) => { const v = params.get(k); if (v) carry.set(k, v); });
  const suffix = carry.toString() ? `?${carry}` : "";
  const isOn = (it: Item) => (it.exact ? path === it.href : path === it.href || path.startsWith(it.href + "/"));

  return (
    <aside className="side" aria-label="TrustAI navigation">
      <div className="side-top">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="logo light" src="/randomtrees-logo.png" alt="RandomTrees" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="logo dark" src="/randomtrees-logo-light.png" alt="RandomTrees" />
        <button type="button" className="icon-btn sm" onClick={onToggle} aria-label="Collapse sidebar"><PanelLeft className="ic" /></button>
      </div>
      <div className="switcher" aria-label="Product: TrustAI, AI governance and observability">
        <span className="mark" aria-hidden><ShieldCheck className="ic" /></span>
        <span className="t lbl"><b>TrustAI</b><small>AI governance & observability</small></span>
      </div>
      <nav className="nav" aria-label="Primary">
        {GROUPS.map((g) => (
          <div key={g.id}>
            <button type="button" className="nav-h" aria-expanded={!closed[g.id]} aria-controls={`nav-${g.id}`} onClick={() => setClosed((c) => ({ ...c, [g.id]: !c[g.id] }))}>
              <span className="lbl">{g.label}</span><ChevronDown className="ic" aria-hidden />
            </button>
            <ul id={`nav-${g.id}`} hidden={closed[g.id]}>
              {g.items.map((it) => (
                <li key={it.href}>
                  <Link href={it.href + suffix} aria-current={isOn(it) ? "page" : undefined} title={it.label}>
                    <it.icon className="ic" aria-hidden /><span className="lbl">{it.label}</span>
                    {it.badge === "alerts" && !!alerts.data && <span className="count" aria-label={`${alerts.data} active alerts`}>{alerts.data}</span>}
                    {it.live && <span className="live-dot" aria-label="Live" />}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className="side-foot">
        <ul>
          <li><a href="https://github.com/vickyuxdev/TrustAI-New#readme" target="_blank" rel="noreferrer" title="Help and docs"><CircleHelp className="ic" aria-hidden /><span className="lbl">Help & docs</span></a></li>
        </ul>
        <div className="me">
          <span className="ico" aria-hidden style={{ width: 28, height: 28, borderRadius: "50%", display: "grid", placeItems: "center", background: "var(--accent-soft)", color: "var(--accent-text)", border: "1px solid var(--accent-line)", fontSize: 11, fontWeight: 600, flex: "none" }}>RT</span>
          <span className="t lbl"><b>RandomTrees</b><small>Platform admin</small></span>
        </div>
      </div>
    </aside>
  );
}
