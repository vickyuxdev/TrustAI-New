"use client";
import { useEffect, useRef, useState } from "react";
import { useIsDark } from "@/lib/clientState";
import { usePathname, useRouter } from "next/navigation";
import { Moon, Search, Sun } from "lucide-react";

const TITLES: [RegExp, string, string][] = [
  [/^\/$/, "Observability", "Dashboard"],
  [/^\/projects\/.+/, "Projects", "Project"],
  [/^\/projects/, "Observability", "Projects"],
  [/^\/agents/, "Observability", "Agents"],
  [/^\/traces/, "Observability", "Traces"],
  [/^\/clients/, "Observability", "Clients"],
  [/^\/cost/, "Observability", "Cost Insights"],
  [/^\/governance\/agents\/.+/, "Agent Registry", "Agent"],
  [/^\/governance\/agents/, "Governance", "Agent Registry"],
  [/^\/governance\/risk\/.+/, "Risk Assessments", "Assessment"],
  [/^\/governance\/risk/, "Governance", "Risk Assessments"],
  [/^\/governance\/policies/, "Governance", "Policies & Guardrails"],
  [/^\/governance\/evaluations\/.+/, "Red-Team", "Run"],
  [/^\/governance\/evaluations/, "Governance", "Red-Team"],
  [/^\/governance\/gateway/, "Governance", "AI Gateway"],
  [/^\/governance\/events/, "Governance", "Audit Events"],
  [/^\/governance/, "Governance", "Overview"],
  [/^\/alerts/, "Settings", "Alerts"],
  [/^\/settings\/connectors/, "Settings", "Connectors"],
  [/^\/settings\/onboarding/, "Settings", "SDK & API Keys"],
  [/^\/settings\/pricing/, "Settings", "Model Pricing"],
];

export function TopBar() {
  const path = usePathname();
  const router = useRouter();
  const [q, setQ] = useState("");
  const dark = useIsDark();
  const input = useRef<HTMLInputElement>(null);
  const [section, page] = (TITLES.find(([re]) => re.test(path)) ?? [null, "TrustAI", ""]).slice(1) as [string, string];

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(t.tagName) && !t.isContentEditable) { e.preventDefault(); input.current?.focus(); }
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
    try { localStorage.setItem("aif-theme", next ? "dark" : "light"); } catch { /* storage blocked */ }
  };

  return (
    <header className="topbar">
      <div className="crumbs"><span>{section}</span>{page && <><span className="sep">/</span><b>{page}</b></>}</div>
      <div className="top-r">
        <form className="search" role="search" onSubmit={(e) => {
          e.preventDefault();
          const v = q.trim();
          if (!v) return;
          router.push(/^[0-9a-f]{16,32}$/i.test(v) ? `/traces?trace=${encodeURIComponent(v)}` : `/traces?q=${encodeURIComponent(v)}`);
        }}>
          <Search className="ic" aria-hidden />
          <label className="sr" htmlFor="global-search">Search traces</label>
          <input id="global-search" ref={input} type="search" placeholder="Search traces, models or trace IDs" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
          <kbd aria-hidden>/</kbd>
        </form>
        <button type="button" className="icon-btn" onClick={toggleTheme} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
          {dark ? <Sun className="ic" /> : <Moon className="ic" />}
        </button>
      </div>
    </header>
  );
}
