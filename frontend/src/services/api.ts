import type { Session } from "../types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

let session: Session | null = null;
type Listener = () => void;
const expiryListeners = new Set<Listener>();

/** Decode the exp claim for UI timing only. The server remains the authority on token validity. */
export function tokenExpiry(token: string): number | null {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(payload.padEnd(payload.length + ((4 - (payload.length % 4)) % 4), "=")));
    return typeof claims.exp === "number" ? claims.exp : null;
  } catch {
    return null;
  }
}

export function setSession(next: Session | null): void {
  session = next;
  try {
    if (next) sessionStorage.setItem("eaop.session", JSON.stringify(next));
    else sessionStorage.removeItem("eaop.session");
  } catch {
    /* storage unavailable: keep in memory only */
  }
}

export function getSession(): Session | null {
  if (session) return session;
  try {
    const raw = sessionStorage.getItem("eaop.session");
    if (raw) session = JSON.parse(raw) as Session;
  } catch {
    /* ignore */
  }
  return session;
}

/** Called when the server rejects the current token (401) so the shell can show "session expired". */
export function onSessionExpired(listener: Listener): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

export async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const err = body.error ?? {};
    const detail = Array.isArray(err.details)
      ? `: ${err.details.map((d: { loc?: unknown[]; msg: string }) => `${(d.loc ?? []).slice(1).join(".") || "value"} ${d.msg}`).join("; ")}`
      : "";
    return new ApiError(res.status, err.code ?? "error", `${err.message ?? res.statusText}${detail}`);
  } catch {
    return new ApiError(res.status, "error", res.statusText || "Request failed");
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const current = getSession();
  if (current) headers.set("Authorization", `Bearer ${current.token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the server");
  }
  if (res.status === 401 && current) {
    setSession(null);
    expiryListeners.forEach((l) => l());
  }
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

const body = (value: unknown) => (value === undefined ? undefined : JSON.stringify(value));
export const post = <T,>(path: string, value?: unknown) => api<T>(path, { method: "POST", body: body(value) });
export const put = <T,>(path: string, value?: unknown) => api<T>(path, { method: "PUT", body: body(value) });
export const patch = <T,>(path: string, value?: unknown) => api<T>(path, { method: "PATCH", body: body(value) });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });

/** Build a query string from defined, non-empty values only. */
export function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface LoginResponse {
  access_token: string;
  role: string;
  tenant_id: string | null;
  user: { id: string; email: string };
}

export async function login(tenant: string, email: string, password: string): Promise<Session> {
  let res: Response;
  try {
    res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, ...(tenant.trim() ? { tenant: tenant.trim() } : {}) }),
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the server");
  }
  if (!res.ok) throw await parseError(res);
  const data = (await res.json()) as LoginResponse;
  const next: Session = {
    token: data.access_token,
    role: data.role,
    tenant: tenant.trim(),
    tenantId: data.tenant_id,
    email: data.user.email,
    userId: data.user.id,
    expiresAt: tokenExpiry(data.access_token),
  };
  setSession(next);
  return next;
}
