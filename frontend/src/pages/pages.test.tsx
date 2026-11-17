import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import AppLayout from "../layouts/AppLayout";
import { setSession } from "../services/api";
import { errorResponse, incident, mockApi, page, signIn, ticket } from "../../tests/utils";
import ApprovalsPage from "./ApprovalsPage";
import DocumentsPage from "./DocumentsPage";
import IncidentsPage from "./IncidentsPage";
import LoginPage from "./LoginPage";
import TicketsPage from "./TicketsPage";

beforeEach(() => { window.location.hash = ""; });
afterEach(() => { vi.restoreAllMocks(); setSession(null); });

const noProfile = { version: 0, using_defaults: true, profile: null, updated_at: null };

it("moves keyboard focus from the skip link into main content", async () => {
  const user = userEvent.setup();
  render(<AppLayout session={signIn("tenant_admin")} pages={[]} path="/overview" expiringSoon={false} onSignOut={() => {}}>
    <button>First content action</button>
  </AppLayout>);
  await user.tab();
  expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("main")).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "First content action" })).toHaveFocus();
});

describe("LoginPage", () => {
  it("validates before calling the server and shows the expiry notice", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    render(<LoginPage onLogin={() => {}} expiredNotice />);
    expect(screen.getByText(/session expired/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("shows the server's error for bad credentials and a throttle hint for 429", async () => {
    mockApi({ "POST /auth/login": () => errorResponse(429, "too_many_attempts", "Too many failed sign-in attempts") });
    render(<LoginPage onLogin={() => {}} />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Too many failed sign-in attempts.*Wait a minute/);
  });
});

describe("App shell", () => {
  it("shows role-appropriate navigation and tenant identity", async () => {
    signIn("support_engineer");
    mockApi({
      "GET /metrics": { tickets_by_state: {}, incidents_by_review_status: {}, incidents_by_priority: {}, outbox_by_status: {}, documents_by_kind: {}, documents: 0, incidents: 0, dead_letters: 0, submission_attempts: 0, tickets_needing_retries: 0, approvals_decided: 0, avg_approval_turnaround_seconds: null },
      "GET /tenant-profile": noProfile, "GET /onboarding/health": { checks: [], passed: 0, total: 0 }, "GET /approvals": page([]), "GET /tickets": page([]),
    });
    window.location.hash = "#/overview";
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link")).toHaveLength(11);
    expect(within(nav).queryByRole("link", { name: "Audit Logs" })).toBeNull();
    expect(screen.getByText("acme")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
  });

  it("explains a page that is not available to the role, noting the server enforces access", () => {
    signIn("support_engineer");
    mockApi({});
    window.location.hash = "#/audit";
    render(<App />);
    expect(screen.getByRole("heading", { name: "Not available for your role" })).toBeInTheDocument();
    expect(screen.getByText(/server enforces access independently/)).toBeInTheDocument();
  });

  it("returns to sign-in with an explanation when the server rejects the token (session expiry)", async () => {
    signIn("tenant_admin");
    mockApi({ "GET /metrics": () => errorResponse(401, "token_expired", "Token expired"), "GET /tenant-profile": () => errorResponse(401, "token_expired", "Token expired"),
      "GET /onboarding/health": () => errorResponse(401, "token_expired", "Token expired"), "GET /approvals": () => errorResponse(401, "token_expired", "Token expired"),
      "GET /tickets": () => errorResponse(401, "token_expired", "Token expired"), "GET /audit": () => errorResponse(401, "token_expired", "Token expired") });
    window.location.hash = "#/overview";
    render(<App />);
    expect(await screen.findByText(/session expired or was rejected/i)).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Sign in" })).toBeInTheDocument();
  });

  it("gives platform administrators only the Administration page", () => {
    signIn("platform_admin", { tenant: "", tenantId: null });
    mockApi({ "GET /platform/audit": { items: [] } });
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Administration"]);
  });
});

describe("TicketsPage", () => {
  function setup(role: string, t: Record<string, unknown>) {
    signIn(role);
    window.location.hash = `#/tickets?id=${t.id as string}`;
    return mockApi({
      "GET /tickets": page([t]), [`GET /tickets/${t.id as string}`]: t, [`GET /tickets/${t.id as string}/history`]: { ticket_id: t.id, events: [], approvals: [] },
      [`POST /tickets/${t.id as string}/request-approval`]: ticket({ state: "PENDING_APPROVAL" }),
    });
  }

  it("lets an engineer edit a draft and request approval only after confirming", async () => {
    const api = setup("support_engineer", ticket());
    render(<TicketsPage session={signIn("support_engineer")} />);
    await userEvent.click(await screen.findByRole("button", { name: "Request approval…" }));
    expect(api.posts()).toHaveLength(0);
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Request approval" }));
    await waitFor(() => expect(api.posts().map((c) => c.path)).toEqual(["/tickets/t-1/request-approval"]));
    expect(await screen.findByText(/different person must approve/)).toBeInTheDocument();
  });

  it("does not claim success for an approved ticket the worker has not sent", async () => {
    setup("tenant_admin", ticket({ state: "APPROVED" }));
    render(<TicketsPage session={signIn("tenant_admin")} />);
    expect(await screen.findByText(/Approved, but not yet sent/)).toBeInTheDocument();
    expect(screen.queryByText(/Confirmed by the external system/)).toBeNull();
  });

  it("shows the confirmed external id only for a submitted ticket", async () => {
    setup("tenant_admin", ticket({ state: "SUBMITTED", external_ticket_id: "WO-7001", submitted_at: "2026-01-01T10:05:00Z" }));
    render(<TicketsPage session={signIn("tenant_admin")} />);
    expect(await screen.findByText(/Confirmed by the external system/)).toHaveTextContent("WO-7001");
  });

  it("shows the failure reason and offers retry only to roles allowed to retry", async () => {
    const failed = ticket({ state: "FAILED", attempts: 5, last_error: "transient: HTTP 503" });
    setup("support_engineer", failed);
    const { unmount } = render(<TicketsPage session={signIn("support_engineer")} />);
    expect(await screen.findByText(/Submission failed after 5 attempt/)).toHaveTextContent("HTTP 503");
    expect(screen.queryByRole("button", { name: "Retry submission…" })).toBeNull();
    unmount();
    setup("maintenance_supervisor", failed);
    render(<TicketsPage session={signIn("maintenance_supervisor")} />);
    expect(await screen.findByRole("button", { name: "Retry submission…" })).toBeInTheDocument();
  });

  it("hides write actions from read-only auditors", async () => {
    setup("read_only_auditor", ticket());
    render(<TicketsPage session={signIn("read_only_auditor")} />);
    await screen.findByText("Content sent to the external system");
    expect(screen.queryByRole("button", { name: /Request approval/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cancel ticket/ })).toBeNull();
  });
});

describe("ApprovalsPage", () => {
  const pendingTicket = ticket({ state: "PENDING_APPROVAL", created_by: "user-support_engineer" });
  const routes = (decide?: () => unknown) => mockApi({
    "GET /approvals": page([pendingTicket]), "GET /incidents/i-1": incident({ review_status: "accepted", notes: ["Human review: accepted by a supervisor. Justification: ok"] }),
    "POST /approvals/t-1/decision": decide ?? { ...pendingTicket, state: "APPROVED" },
  });

  it("blocks the author from deciding on their own ticket (separation of duties)", async () => {
    routes();
    render(<ApprovalsPage session={signIn("maintenance_supervisor", { userId: "user-support_engineer" })} />);
    expect(await screen.findByText(/you cannot decide on it/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve…" })).toBeNull();
  });

  it("shows context, distinguishes human review from AI text, and requires confirmation before approving", async () => {
    const api = routes();
    render(<ApprovalsPage session={signIn("maintenance_supervisor")} />);
    expect(await screen.findByText("Human-reviewed")).toBeInTheDocument();
    expect(screen.getAllByText("AI-generated").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Approve…" }));
    expect(api.posts()).toHaveLength(0);
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.posts()[0]).toMatchObject({ path: "/approvals/t-1/decision", body: { decision: "approved" } }));
    expect(await screen.findByText(/only when the external system confirms/)).toBeInTheDocument();
  });

  it("surfaces a server refusal (for example an unregistered asset) instead of pretending success", async () => {
    routes(() => errorResponse(409, "asset_not_registered", "Asset P-101 is not in the tenant's authoritative register"));
    render(<ApprovalsPage session={signIn("tenant_admin")} />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/not in the tenant's authoritative register/)).toBeInTheDocument();
    expect(screen.queryByText(/Approved\. The ticket is queued/)).toBeNull();
  });

  it.each(["Approve", "Reject"])("keeps focus in the queue after confirming %s", async (action) => {
    const user = userEvent.setup();
    let pending = true;
    mockApi({
      "GET /approvals": () => page(pending ? [pendingTicket] : []),
      "GET /incidents/i-1": incident(),
      "POST /approvals/t-1/decision": () => { pending = false; return {}; },
    });
    render(<ApprovalsPage session={signIn("tenant_admin")} />);
    const trigger = await screen.findByRole("button", { name: `${action}…` });
    trigger.focus();
    await user.keyboard("{Enter}");
    expect(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.tab();
    expect(within(screen.getByRole("alertdialog")).getByRole("button", { name: action })).toHaveFocus();
    await user.keyboard("{Enter}");
    await screen.findByText("Nothing is waiting for approval.");
    expect(trigger).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Awaiting decision/ })).toHaveFocus();
  });

  it("warns when the asset is not verified", async () => {
    mockApi({ "GET /approvals": page([pendingTicket]), "GET /incidents/i-1": incident({ asset_verified: false, review_status: "accepted" }) });
    render(<ApprovalsPage session={signIn("tenant_admin")} />);
    expect(await screen.findByText(/asset NOT in register/)).toBeInTheDocument();
  });

  it("offers no decision controls to engineers", async () => {
    routes();
    render(<ApprovalsPage session={signIn("support_engineer", { userId: "someone-else" })} />);
    expect(await screen.findByText(/cannot decide on approvals/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve…" })).toBeNull();
  });
});

describe("IncidentsPage review gate", () => {
  function setup(role: string, inc = incident()) {
    window.location.hash = `#/incidents?id=${inc.id}`;
    const session = signIn(role);
    const api = mockApi({
      "GET /tenant-profile": noProfile, "GET /incidents": page([inc]), [`GET /incidents/${inc.id}`]: inc,
      [`GET /incidents/${inc.id}/history`]: { incident_id: inc.id, events: [], tickets: [] },
      [`POST /incidents/${inc.id}/review`]: { ...inc, review_status: "accepted" },
    });
    return { api, session };
  }

  it("shows a blocked incident without a ticket button, and no review controls for engineers", async () => {
    const { session } = setup("support_engineer");
    render(<IncidentsPage session={session} />);
    expect(await screen.findByText(/This incident is blocked/)).toBeInTheDocument();
    expect(screen.getByText(/Only supervisors and tenant administrators can review/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Create ticket draft/ })).toBeNull();
  });

  it("requires a written justification and a confirmation before accepting, and says acceptance does not verify claims", async () => {
    const { api, session } = setup("maintenance_supervisor");
    render(<IncidentsPage session={session} />);
    await userEvent.click(await screen.findByRole("button", { name: "Accept for ticketing…" }));
    expect(await screen.findByText(/Write a justification/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await userEvent.type(screen.getByLabelText(/Justification/), "Checked on site, pump verified");
    await userEvent.click(screen.getByRole("button", { name: "Accept for ticketing…" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText(/does not make unsupported AI statements true/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Accept incident" }));
    await waitFor(() => expect(api.posts()[0]).toMatchObject({ path: "/incidents/i-1/review", body: { decision: "accept", comment: "Checked on site, pump verified" } }));
  });

  it("labels AI-generated extraction separately from retrieved evidence and flags an unregistered asset", async () => {
    const { session } = setup("tenant_admin", incident({ asset_verified: false, review_status: "accepted", citations: [] }));
    render(<IncidentsPage session={session} />);
    expect(await screen.findByText("equipment NOT in register")).toBeInTheDocument();
    expect(screen.getAllByText("AI-generated").length).toBeGreaterThan(0);
    expect(screen.getByText(/cannot be approved or sent until the equipment is registered/)).toBeInTheDocument();
    expect(screen.getByText("No verified citations support this recommendation.")).toBeInTheDocument();
  });
});

describe("DocumentsPage upload validation", () => {
  it("rejects unsupported and oversized files before contacting the server", async () => {
    const session = signIn("support_engineer");
    mockApi({ "GET /tenant-profile": noProfile, "GET /documents": page([]) });
    render(<DocumentsPage session={session} />);
    const input = await screen.findByLabelText(/File \(PDF/);
    await userEvent.upload(input, new File(["x"], "notes.exe"), { applyAccept: false });
    expect(await screen.findByText(/Unsupported file type \.exe/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ingest" })).toBeDisabled();
    await userEvent.upload(input, new File([new Uint8Array(10 * 1024 * 1024 + 1)], "big.pdf"), { applyAccept: false });
    expect(await screen.findByText("File is larger than 10 MB.")).toBeInTheDocument();
  });

  it("hides ingestion from read-only auditors", async () => {
    const session = signIn("read_only_auditor");
    mockApi({ "GET /tenant-profile": noProfile, "GET /documents": page([]) });
    render(<DocumentsPage session={session} />);
    await screen.findByText("No documents yet.");
    expect(screen.queryByRole("form", { name: "Upload document" })).toBeNull();
  });
});
