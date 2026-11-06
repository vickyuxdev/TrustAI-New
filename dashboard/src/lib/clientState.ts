"use client";
/** Small browser-backed state hooks built on useSyncExternalStore (SSR-safe, no effects). */
import { useSyncExternalStore } from "react";

const EVT = "ta-local-store";

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

/** A localStorage-backed boolean flag ("1"/"0"); server render always sees `false`. */
export function useStoredFlag(key: string): [boolean, (v: boolean) => void] {
  const value = useSyncExternalStore(
    (cb) => {
      const h = (e: Event) => { if (!(e instanceof StorageEvent) || e.key === key) cb(); };
      window.addEventListener("storage", h);
      window.addEventListener(EVT, h);
      return () => { window.removeEventListener("storage", h); window.removeEventListener(EVT, h); };
    },
    () => read(key) === "1",
    () => false,
  );
  const set = (v: boolean) => {
    try { localStorage.setItem(key, v ? "1" : "0"); } catch { /* storage blocked */ }
    window.dispatchEvent(new Event(EVT));
  };
  return [value, set];
}

/** Whether the document is currently in dark theme (tracks the data-theme attribute). */
export function useIsDark(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mo = new MutationObserver(cb);
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      return () => mo.disconnect();
    },
    () => document.documentElement.getAttribute("data-theme") === "dark",
    () => false,
  );
}
