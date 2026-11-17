import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../services/api";
import { mockApi, page, signIn } from "../../tests/utils";
import DataSourcesPage from "./DataSourcesPage";
import IntegrationHealthPage from "./IntegrationHealthPage";

beforeEach(() => { window.location.hash = ""; });
afterEach(() => { vi.restoreAllMocks(); setSession(null); });

const connectors = {
  items: [
    { id: "c-rest", kind: "rest", name: "bulletins-rest", base_url: "http://127.0.0.1:8106", has_secret: true, config: { records: { path: "/v1/apex/cursor", id_field: "id" } } },
    { id: "c-csv", kind: "csv", name: "export-csv", base_url: "http://127.0.0.1:8106", has_secret: true, config: { csv: { path: "/v1/apex-csv/csv", id_field: "id" } } },
    { id: "c-tk", kind: "ticketing", name: "tickets", base_url: "http://127.0.0.1:8101", has_secret: true, config: {} },
  ],
};
const health = { items: connectors.items.map((c) => ({ id: c.id, kind: c.kind, name: c.name, base_url: c.base_url, status: "ok", destination_authorized: true, destination_reason: null, secret_configured: true, has_secret_ref: true, probe: "none: configuration only" })) };
const job = (over: Record<string, unknown> = {}) => ({
  id: "j-1", job_type: "sync", status: "COMPLETED", filename: "bulletins-rest", attempts: 1, max_attempts: 5, error_code: null, outcome: "synced", connector_id: "c-rest", endpoint_id: null,
  sync: { pages: 3, seen: 7, created: 7, updated: 0, unchanged: 0, linked_duplicate: 0, skipped_deleted: 0, tombstoned_changed: 0, duplicate_in_sync: 0, conflict: 0, invalid: 0, rejections: {}, truncated: false },
  created_at: "2026-01-01T10:00:00Z", ...over,
});
const endpoint = (over: Record<string, unknown> = {}) => ({ id: "w-1", name: "bulletin-feed", status: "active", receive_path: "/api/v1/webhooks/w-1", secret_configured: true, has_previous_secret: false, config: { id_field: "id" }, created_at: "2026-01-01T10:00:00Z", updated_at: "2026-01-01T10:00:00Z", ...over });
const baseHandlers = (extra: Record<string, unknown> = {}) => ({
  "GET /metrics": { documents_by_kind: {}, tickets_by_state: {} }, "GET /connectors": connectors, "GET /connectors/health": health,
  "GET /ingestion/jobs": (req: { query: URLSearchParams }) => page(req.query.get("job_type") === "sync" ? [job()] : req.query.get("job_type") === "webhook" ? [job({ id: "j-2", job_type: "webhook", filename: "bulletin-feed", connector_id: null, endpoint_id: "w-1", created_at: "2026-01-02T10:00:00Z" })] : []),
  "GET /webhook-endpoints": { items: [endpoint()] }, ...extra,
});

describe("Data Sources: synchronisation and activity", () => {
  it("offers Synchronise only for configured REST and CSV connectors, queues a job and shows a plain message", async () => {
    signIn("tenant_admin");
    const api = mockApi(baseHandlers({ "POST /connectors/c-rest/sync": { ...job({ status: "QUEUED", outcome: null, sync: null }) } }));
    render(<DataSourcesPage session={signIn("tenant_admin")} />);
    expect(await screen.findByRole("button", { name: "Synchronise bulletins-rest" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Synchronise export-csv" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Synchronise tickets/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Synchronise bulletins-rest" }));
    expect(await screen.findByText(/queued .*processed by the worker/i)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/connectors/c-rest/sync" && c.body === undefined)).toBe(true);  // no body: the destination comes only from the stored connector
  });

  it("shows recent synchronisations and webhook deliveries as counts, never content", async () => {
    signIn("tenant_admin");
    mockApi(baseHandlers());
    render(<DataSourcesPage session={signIn("tenant_admin")} />);
    const card = (await screen.findByRole("heading", { name: "Recent synchronisations and webhook deliveries" })).closest("section, article, div")!.parentElement!;
    expect((await within(card).findAllByText(/synced: 7 created, 0 updated, 0 unchanged, 0 rejected, 0 kept deleted/)).length).toBe(2);  // one sync job and one webhook delivery
    expect(within(card).getAllByRole("row").length).toBeGreaterThanOrEqual(3);
    expect(within(card).getByText("webhook")).toBeInTheDocument();
  });

  it("a supervisor sees the activity but neither the connector list nor webhook administration", async () => {
    mockApi(baseHandlers());
    render(<DataSourcesPage session={signIn("maintenance_supervisor")} />);
    expect(await screen.findByText(/Connector configuration is visible to tenant administrators only/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Recent synchronisations and webhook deliveries" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Webhook endpoints" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Synchronise/ })).not.toBeInTheDocument();
  });
});

describe("Data Sources: webhook endpoints", () => {
  it("validates locally, never asks for a secret value, and creates an endpoint only after confirmation", async () => {
    const api = mockApi(baseHandlers({ "POST /webhook-endpoints": endpoint({ name: "new-feed", id: "w-2", receive_path: "/api/v1/webhooks/w-2" }) }));
    render(<DataSourcesPage session={signIn("tenant_admin")} />);
    await screen.findByRole("heading", { name: "Add a webhook endpoint" });
    const form = screen.getByRole("form", { name: "Add webhook endpoint" });
    await userEvent.type(within(form).getByLabelText("Endpoint name"), "new-feed");
    await userEvent.type(within(form).getByLabelText(/Signing secret variable name/), "not-a-name");
    await userEvent.click(within(form).getByRole("button", { name: "Review and add…" }));
    expect(await within(form).findByText(/^Enter the NAME of a server environment variable/)).toBeInTheDocument();
    expect(api.posts()).toHaveLength(0);
    const secret = within(form).getByLabelText(/Signing secret variable name/);
    await userEvent.clear(secret);
    await userEvent.type(secret, "PARTNER_WEBHOOK_SECRET");
    const config = within(form).getByLabelText(/Record configuration/);
    await userEvent.clear(config);
    await userEvent.click(config);
    await userEvent.paste("{}");
    await userEvent.click(within(form).getByRole("button", { name: "Review and add…" }));
    expect(await within(form).findByText(/needs an id_field/)).toBeInTheDocument();
    expect(api.posts()).toHaveLength(0);
    await userEvent.clear(config);
    await userEvent.click(config);
    await userEvent.paste('{"id_field":"id"}');
    await userEvent.click(within(form).getByRole("button", { name: "Review and add…" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add endpoint" }));
    await waitFor(() => expect(api.posts()).toHaveLength(1));
    expect(api.posts()[0]).toMatchObject({ method: "POST", path: "/webhook-endpoints", body: { name: "new-feed", secret_ref: "PARTNER_WEBHOOK_SECRET", config: { id_field: "id" } } });
    expect(await screen.findByText(/Senders post signed deliveries to \/api\/v1\/webhooks\/w-2/)).toBeInTheDocument();
  });

  it("disables, rotates and drops the previous secret through PATCH, and shows only whether the server has the secret", async () => {
    const state = { rotated: false };
    const api = mockApi(baseHandlers({
      "GET /webhook-endpoints": () => ({ items: [endpoint({ has_previous_secret: state.rotated })] }),
      "PATCH /webhook-endpoints/w-1": (req: { body: unknown }) => { if ((req.body as Record<string, unknown>).secret_ref) state.rotated = true; return endpoint(); },
    }));
    render(<DataSourcesPage session={signIn("tenant_admin")} />);
    expect(await screen.findByText("configured on the server")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(api.posts().some((c) => c.method === "PATCH" && (c.body as Record<string, unknown>).status === "disabled")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Rotate secret of bulletin-feed" }));
    const rotate = screen.getByRole("form", { name: "Rotate secret of bulletin-feed" });
    await userEvent.type(within(rotate).getByLabelText("New secret variable name"), "PARTNER_WEBHOOK_SECRET_NEXT");
    await userEvent.click(within(rotate).getByRole("button", { name: "Rotate" }));
    await waitFor(() => expect(api.posts().some((c) => (c.body as Record<string, unknown>).secret_ref === "PARTNER_WEBHOOK_SECRET_NEXT")).toBe(true));
    expect(await screen.findByText(/previous secret still accepted/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Drop previous secret" }));
    await waitFor(() => expect(api.posts().some((c) => (c.body as Record<string, unknown>).drop_previous_secret === true)).toBe(true));
  });
});

describe("Integration Health: opt-in live probe", () => {
  it("makes no probe request until the administrator asks, then shows the probe class per connector", async () => {
    const api = mockApi({
      "GET /health": { status: "ok" }, "GET /metrics": { tickets_by_state: {}, documents_by_kind: {}, tickets_needing_retries: 0, submission_attempts: 0, dead_letters: 0 }, "GET /observability/summary": null,
      "GET /connectors/health": (req: { query: URLSearchParams }) => req.query.get("probe") === "true"
        ? { items: health.items.map((c) => (c.id === "c-rest" ? { ...c, status: "degraded", live_probe: { status: "authentication", http_status: 401, duration_ms: 12.5, checked_at: "2026-01-01T10:00:00Z" } } : c)) }
        : health,
    });
    render(<IntegrationHealthPage session={signIn("tenant_admin")} />);
    await screen.findByRole("button", { name: "Run live probe" });
    expect(api.calls.some((c) => c.query.get("probe") === "true")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Run live probe" }));
    expect(await screen.findByText(/authentication \(12.5 ms, HTTP 401\)/)).toBeInTheDocument();
    expect(api.calls.filter((c) => c.query.get("probe") === "true")).toHaveLength(1);
  });

  it("does not offer the probe to a role that cannot see connectors", async () => {
    mockApi({ "GET /health": { status: "ok" }, "GET /metrics": { tickets_by_state: {}, documents_by_kind: {}, tickets_needing_retries: 0, submission_attempts: 0, dead_letters: 0 }, "GET /observability/summary": null });
    render(<IntegrationHealthPage session={signIn("maintenance_supervisor")} />);
    await screen.findByText(/Per-connector status is visible to tenant administrators only/);
    expect(screen.queryByRole("button", { name: "Run live probe" })).not.toBeInTheDocument();
  });
});
