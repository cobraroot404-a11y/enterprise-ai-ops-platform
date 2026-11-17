import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, getSession, login, onSessionExpired, parseError, qs, setSession, tokenExpiry } from "./api";
import { signIn } from "../../tests/utils";

afterEach(() => {
  vi.restoreAllMocks();
  setSession(null);
});

const jwt = (claims: object) => `h.${btoa(JSON.stringify(claims)).replace(/=/g, "")}.s`;

describe("api client", () => {
  it("parses the standardized error shape including validation details", async () => {
    const res = new Response(JSON.stringify({ error: { code: "validation_error", message: "bad", details: [{ loc: ["body", "name"], msg: "too short" }] } }), { status: 422 });
    const err = await parseError(res);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("validation_error");
    expect(err.message).toContain("name too short");
  });

  it("sends the bearer token, clears the session and notifies listeners on 401", async () => {
    signIn("support_engineer", { token: "abc" });
    const expired = vi.fn();
    const off = onSessionExpired(expired);
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code: "token_expired", message: "expired" } }), { status: 401 }));
    await expect(api("/documents")).rejects.toThrow("expired");
    expect((spy.mock.calls[0][1]?.headers as Headers).get("Authorization")).toBe("Bearer abc");
    expect(expired).toHaveBeenCalledTimes(1);
    expect(getSession()).toBeNull();
    off();
  });

  it("reports network failures", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("down"));
    await expect(api("/health")).rejects.toMatchObject({ code: "network" });
  });

  it("builds query strings from defined values only", () => {
    expect(qs({ a: "x", b: "", c: undefined, d: 0, e: null })).toBe("?a=x&d=0");
    expect(qs({})).toBe("");
  });

  it("reads the token expiry for UI timing and tolerates garbage", () => {
    expect(tokenExpiry(jwt({ exp: 1234 }))).toBe(1234);
    expect(tokenExpiry("not-a-token")).toBeNull();
  });

  it("login stores the session with tenant, role and expiry and omits an empty tenant", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      access_token: jwt({ exp: 9999999999 }), role: "platform_admin", tenant_id: null, user: { id: "u1", email: "p@x.test" } }), { status: 200 }));
    const s = await login("  ", "p@x.test", "secret-secret");
    expect(JSON.parse(String(spy.mock.calls[0][1]?.body))).toEqual({ email: "p@x.test", password: "secret-secret" });
    expect(s).toMatchObject({ role: "platform_admin", tenantId: null, userId: "u1", expiresAt: 9999999999 });
    expect(getSession()?.email).toBe("p@x.test");
  });
});
