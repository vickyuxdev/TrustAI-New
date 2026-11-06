/**
 * /api/admin/* → TrustAI Admin service (/api/v1/*).
 * Host: INTERNAL_ADMIN_URL (docker-compose → admin:8000), else NEXT_PUBLIC_ADMIN_URL, else localhost:8003.
 */
import { makeProxy } from "@/lib/server/proxy";

const proxy = makeProxy(
  process.env.INTERNAL_ADMIN_URL || process.env.NEXT_PUBLIC_ADMIN_URL || "http://localhost:8003",
  "Admin",
);

export const { GET, POST, PUT, PATCH, DELETE } = proxy;
