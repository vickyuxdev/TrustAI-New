"use client";
import { Suspense, type ReactNode } from "react";
import { useStoredFlag } from "@/lib/clientState";
import { QueryProvider } from "@/components/QueryProvider";
import { ToastProvider } from "@/components/ui";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function Shell({ children }: { children: ReactNode }) {
  const [mini, setMini] = useStoredFlag("ta-side-mini");
  const toggle = () => setMini(!mini);
  return (
    <QueryProvider>
      <ToastProvider>
        <div className={`app${mini ? " mini" : ""}`}>
          <Suspense fallback={<aside className="side" />}><Sidebar onToggle={toggle} /></Suspense>
          <div className="panel">
            <TopBar />
            <main className="content" id="main"><Suspense fallback={null}>{children}</Suspense></main>
          </div>
        </div>
      </ToastProvider>
    </QueryProvider>
  );
}
