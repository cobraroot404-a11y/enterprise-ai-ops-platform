import { vi } from "vitest";
import { setSession } from "../src/services/api";
import type { Session } from "../src/types";

type Handler = (req: { method: string; path: string; query: URLSearchParams; body: unknown }) => unknown;

/** Stub fetch with per-route handlers keyed "METHOD /path" (no /api/v1 prefix, no query string). */
export function mockApi(handlers: Record<string, Handler | unknown>) {
  const calls: { method: string; path: string; body: unknown; query: URLSearchParams }[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown;
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    else if (init?.body instanceof FormData) body = init.body;
    calls.push({ method, path, body, query: url.searchParams });
    const handler = handlers[`${method} ${path}`];
    if (handler === undefined) return new Response(JSON.stringify({ error: { code: "not_found", message: `no mock for ${method} ${path}` } }), { status: 404 });
    const value = typeof handler === "function" ? await (handler as Handler)({ method, path, query: url.searchParams, body }) : handler;
    if (value instanceof Response) return value;
    return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return { spy, calls, posts: () => calls.filter((c) => c.method !== "GET") };
}

export const page = <T,>(items: T[], total = items.length) => ({ total, limit: 15, offset: 0, items });

export const errorResponse = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ error: { code, message } }), { status });

export function signIn(role: string, over: Partial<Session> = {}): Session {
  const session: Session = {
    token: "tok", role, tenant: "acme", tenantId: "00000000-0000-0000-0000-0000000000aa", email: `${role}@acme.test`,
    userId: `user-${role}`, expiresAt: Math.floor(Date.now() / 1000) + 3600, ...over,
  };
  setSession(session);
  return session;
}

export function ticket(over: Record<string, unknown> = {}) {
  return {
    id: "t-1", incident_id: "i-1", title: "[P2] mechanical vibration on P-101", description: "Asset: P-101", priority: "P2", state: "DRAFT",
    external_ticket_id: null, attempts: 0, last_error: null, created_by: "user-support_engineer", created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z", submitted_at: null, ...over,
  };
}

export function incident(over: Record<string, unknown> = {}) {
  return {
    id: "i-1", asset_id: "P-101", asset_verified: true, category: "mechanical_vibration", symptoms: ["grinding noise"], related_incidents: [],
    priority: "P2", citations: [], recommended_action: "Check coupling alignment.", review_status: "needs_review", notes: [],
    report_text: "Pump P-101 vibrates", extraction_backend: "deterministic/deterministic", created_at: "2026-01-01T10:00:00Z", ...over,
  };
}
