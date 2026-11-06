/**
 * /api/backend/* → TrustAI Analytics API (/api/v1/*).
 * Host: INTERNAL_API_URL (docker-compose → api:8000), else NEXT_PUBLIC_API_URL, else localhost:8002.
 */
import { makeProxy } from "@/lib/server/proxy";

const proxy = makeProxy(
  process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8002",
  "Analytics",
);

export const { GET, POST, PUT, PATCH, DELETE } = proxy;
