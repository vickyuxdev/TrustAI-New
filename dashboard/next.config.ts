import type { NextConfig } from "next";

// API traffic goes through the route handlers in src/app/api/* (backend, admin, governance),
// which read INTERNAL_*_URL at runtime, so no rewrites are needed here.
const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8002",
    NEXT_PUBLIC_ADMIN_URL: process.env.NEXT_PUBLIC_ADMIN_URL || "http://localhost:8003",
    NEXT_PUBLIC_INGESTION_URL: process.env.NEXT_PUBLIC_INGESTION_URL || "http://localhost:8001",
  },
  async redirects() {
    // Clients are not a top-level concept in the UI: old links land on the project list.
    return [
      { source: "/clients", destination: "/projects", permanent: false },
      { source: "/clients/:path*", destination: "/projects", permanent: false },
    ];
  },
};

export default nextConfig;
