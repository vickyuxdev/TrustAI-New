/**
 * /api/governance/* → TrustAI Governance service (/api/v1/*).
 * Host: INTERNAL_GOVERNANCE_URL (docker-compose), else NEXT_PUBLIC_GOVERNANCE_URL, else localhost:8004.
 */
import { makeProxy } from "@/lib/server/proxy";

const proxy = makeProxy(
  process.env.INTERNAL_GOVERNANCE_URL || process.env.NEXT_PUBLIC_GOVERNANCE_URL || "http://localhost:8004",
  "Governance",
);

export const { GET, POST, PUT, PATCH, DELETE } = proxy;
