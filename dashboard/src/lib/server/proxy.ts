/**
 * Server-side proxy shared by the /api/backend, /api/admin and /api/governance route handlers.
 *
 * The browser only talks to the dashboard origin; these handlers forward to the internal
 * service hosts (Docker service names in compose, localhost ports in local dev), pass the
 * Authorization header and query string through, and relay status codes and bodies verbatim.
 * Empty upstream bodies (e.g. 204 from DELETE) are returned as empty responses rather than
 * being parsed as JSON.
 */
import { NextRequest, NextResponse } from "next/server";

export type RouteContext = { params: Promise<{ path: string[] }> };

const SECURITY_HEADERS: Record<string, string> = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

export function makeProxy(baseUrl: string, serviceName: string) {
  const base = baseUrl.replace(/\/+$/, "");

  async function proxy(request: NextRequest, context: RouteContext, method: string) {
    const { path } = await context.params;
    // Encode each segment so user-provided ids can never escape the /api/v1 prefix.
    const pathStr = path.map((p) => encodeURIComponent(p)).join("/");
    const targetUrl = `${base}/api/v1/${pathStr}${request.nextUrl.search}`;

    const headers: Record<string, string> = { Accept: "application/json" };
    const auth = request.headers.get("Authorization");
    if (auth) headers["Authorization"] = auth;

    const init: RequestInit = { method, headers, cache: "no-store" };
    if (method !== "GET" && method !== "HEAD") {
      const raw = await request.text();
      if (raw) {
        headers["Content-Type"] = "application/json";
        init.body = raw;
      }
    }

    let response: Response;
    try {
      response = await fetch(targetUrl, init);
    } catch (err) {
      console.error(`[${serviceName} proxy] ${method} ${targetUrl} failed:`, err);
      return NextResponse.json(
        { detail: `${serviceName} service is unreachable`, error: "service_unreachable" },
        { status: 502, headers: SECURITY_HEADERS },
      );
    }

    if (response.status === 204 || response.status === 304) {
      return new NextResponse(null, { status: response.status, headers: SECURITY_HEADERS });
    }
    const text = await response.text();
    if (!text) {
      return new NextResponse(null, { status: response.status === 200 ? 204 : response.status, headers: SECURITY_HEADERS });
    }
    return new NextResponse(text, {
      status: response.status,
      headers: { ...SECURITY_HEADERS, "Content-Type": response.headers.get("Content-Type") || "application/json" },
    });
  }

  return {
    GET: (r: NextRequest, c: RouteContext) => proxy(r, c, "GET"),
    POST: (r: NextRequest, c: RouteContext) => proxy(r, c, "POST"),
    PUT: (r: NextRequest, c: RouteContext) => proxy(r, c, "PUT"),
    PATCH: (r: NextRequest, c: RouteContext) => proxy(r, c, "PATCH"),
    DELETE: (r: NextRequest, c: RouteContext) => proxy(r, c, "DELETE"),
  };
}
