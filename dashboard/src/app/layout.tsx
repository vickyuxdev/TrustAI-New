import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "./globals.css";
import { Shell } from "@/components/shell/Shell";

export const metadata: Metadata = {
  title: { default: "TrustAI · RandomTrees", template: "%s · TrustAI" },
  description: "RandomTrees TrustAI: observe, cost, govern, red-team and gate every AI agent.",
  icons: { icon: "/randomtrees-mark.png", apple: "/randomtrees-mark.png" },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applies the saved theme before first paint so the page never flashes the wrong colours.
const themeScript = `try{var t=localStorage.getItem('aif-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
