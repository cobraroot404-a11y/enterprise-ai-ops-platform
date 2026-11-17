import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../services/api";
import { errorResponse, incident, mockApi, page, signIn } from "../../tests/utils";
import IncidentsPage from "./IncidentsPage";

beforeEach(() => { window.location.hash = ""; });
afterEach(() => { vi.restoreAllMocks(); setSession(null); });

const noProfile = { version: 0, using_defaults: true, profile: null, updated_at: null };
const ID = "i-1";
const CREATOR = "support_engineer@acme.test";

/** A free-text candidate as the server returns it (class A, UNVERIFIED, not eligible). */
const candidate = (over: Record<string, unknown> = {}) => ({
  name: "vibration_mm_s", status: "unverified", verification_status: "unverified", trust_status: "UNVERIFIED", evidence_class: "A", eligible_for_numeric_priority: false,
  measurement_type: "vibration", asset_id: "P-101", value: null, candidate_value: 8.4, unit: "mm/s", original_value: "8.4", original_unit: "mm/s", source_text: "8.4 mm/s",
  reason: "A number in free text is an unverified candidate; it is not used for priority until a reviewer verifies it.",
  provenance: { source_type: "free_text_report", source_available: true, evidence_span: "8.4 mm/s", extraction_origin: "deterministic_text_analysis", channel: "extract_api", client_source_label: null },
  ...over,
});
/** A structured observation as submitted (class C, VALIDATED, awaiting a human). */
const submitted = (over: Record<string, unknown> = {}) => candidate({
  status: "submitted", verification_status: "submitted", trust_status: "VALIDATED", evidence_class: "C", source_text: "8.4",
  provenance: { source_type: "structured_observation", source_available: true, evidence_span: null, extraction_origin: "authenticated_submission", client_source_label: "gauge GA-7" }, ...over,
});
const verified = (priorityBefore = "P3", priorityAfter = "P2", rule = "numeric_rule") => candidate({
  status: "verified", verification_status: "verified", trust_status: "HUMAN_VERIFIED", evidence_class: "D", eligible_for_numeric_priority: true, value: 8.4,
  verification: { decision: "approve", transition: "UNVERIFIED->HUMAN_VERIFIED", reviewer_id: "u-2", reviewed_at: "2026-01-01T11:00:00Z", comment: "Checked the printout.", priority_before: priorityBefore, priority_after: priorityAfter, applied_rule: rule, audit_event_id: 77 },
});
const inc = (over: Record<string, unknown> = {}) => incident({ review_status: "pending_review", review_urgency: "urgent", priority: "P3", measurements: [candidate()], ...over });
const extractedEvent = { id: 1, action: "incident.extracted", actor: CREATOR, actor_type: "user", details: {}, created_at: "2026-01-01T10:00:00Z" };
const history = (events: unknown[] = [extractedEvent]) => ({ incident_id: ID, events, tickets: [] });

/** Stateful mock: the server holds the incident; POST handlers change it exactly as a server decision would. */
function setup(role: string, start = inc(), overrides: Record<string, unknown> = {}, session = {}) {
  window.location.hash = `#/incidents?id=${ID}`;
  const s = signIn(role, session);
  const state = { incident: start as Record<string, unknown>, events: [extractedEvent] as unknown[] };
  const api = mockApi({
    "GET /tenant-profile": noProfile, "GET /incidents": () => page([state.incident]), [`GET /incidents/${ID}`]: () => state.incident,
    [`GET /incidents/${ID}/history`]: () => history(state.events), ...overrides,
  });
  return { api, state, session: s };
}
const verifyPath = `/incidents/${ID}/measurements/vibration_mm_s/verify`;
const fill = async (text = "Checked the maintenance printout.") => userEvent.type(await screen.findByLabelText(/Justification for vibration/), text);

describe("structured observation form", () => {
  it("validates before calling the server: asset, value, comma decimal and unit", async () => {
    const { api, session } = setup("support_engineer");
    render(<IncidentsPage session={session} />);
    await userEvent.type(await screen.findByLabelText("Fault report"), "Pump P-101 vibrates at the drive end.");
    await userEvent.click(screen.getByRole("button", { name: "Add a structured observation" }));
    await userEvent.click(screen.getByRole("button", { name: "Analyse report" }));
    expect(await screen.findByText("Enter the asset id (2 to 40 characters).")).toBeInTheDocument();
    expect(screen.getByText("Enter the numeric value.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Asset"), "P-101");
    await userEvent.type(screen.getByLabelText("Value"), "8,4");
    await userEvent.click(screen.getByRole("button", { name: "Analyse report" }));
    expect(await screen.findByText("Use a decimal point, not a comma (for example 8.4).")).toBeInTheDocument();
    expect(api.posts()).toHaveLength(0);
  });

  it("sends only the schema's fields (typed number, no trust, reviewer or provenance fields) and the chosen locale", async () => {
    const { api, state, session } = setup("support_engineer", inc({ measurements: [] }), {
      "POST /incidents/extract": () => { state.incident = inc({ id: ID, measurements: [submitted()] }); return state.incident; },
    });
    render(<IncidentsPage session={session} />);
    await userEvent.type(await screen.findByLabelText("Fault report"), "Pump P-101 vibrates at the drive end.");
    await userEvent.selectOptions(screen.getByLabelText(/Number format used in the report text/), "de");
    await userEvent.click(screen.getByRole("button", { name: "Add a structured observation" }));
    await userEvent.type(screen.getByLabelText("Asset"), "P-101");
    await userEvent.type(screen.getByLabelText("Value"), "8.4");
    await userEvent.type(screen.getByLabelText(/Source reference/), "gauge GA-7");
    await userEvent.click(screen.getByRole("button", { name: "Analyse report" }));
    await waitFor(() => expect(api.posts()).toHaveLength(1));
    const body = api.posts()[0].body as Record<string, unknown>;
    expect(api.posts()[0].path).toBe("/incidents/extract");
    expect(body).toEqual({ report_text: "Pump P-101 vibrates at the drive end.", numeric_locale: "de", observations: [{ asset_id: "P-101", measurement_type: "vibration", value: 8.4, unit: "mm/s", source: "gauge GA-7" }] });
    const text = JSON.stringify(body);
    for (const forbidden of ["trust_status", "evidence_class", "verified", "reviewer", "provenance", "simulation", "signature"]) expect(text).not.toContain(forbidden);
  });

  it("shows a submitted observation as awaiting verification, never as verified", async () => {
    const { session } = setup("support_engineer", inc({ measurements: [submitted()] }));
    render(<IncidentsPage session={session} />);
    expect(await screen.findByText("Submitted · awaiting verification")).toBeInTheDocument();
    expect(screen.queryByText("Human-verified")).toBeNull();
    expect(screen.getByText("Not used for priority")).toBeInTheDocument();
    expect(screen.getByText(/Structured observation submitted by “gauge GA-7”/)).toBeInTheDocument();
  });

  it("protects against double submission of the analysis request", async () => {
    let release: (v: unknown) => void = () => {};
    const gate = new Promise((r) => { release = r; });
    const { api, session } = setup("support_engineer", inc(), { "POST /incidents/extract": async () => { await gate; return inc(); } });
    render(<IncidentsPage session={session} />);
    await userEvent.type(await screen.findByLabelText("Fault report"), "Pump P-101 vibrates at the drive end.");
    const button = screen.getByRole("button", { name: "Analyse report" });
    await userEvent.click(button);
    expect(await screen.findByRole("button", { name: "Analysing…" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Analysing…" }));
    release(null);
    await waitFor(() => expect(api.posts().length).toBe(1));
  });
});

describe("measurement review panel", () => {
  it("distinguishes an unverified AI/text candidate: value, asset, source, reason, urgency flag and the server's priority", async () => {
    const { session } = setup("support_engineer");
    render(<IncidentsPage session={session} />);
    expect(await screen.findByText("Unverified candidate")).toBeInTheDocument();
    expect(screen.getAllByText("8.4 mm/s").length).toBeGreaterThan(0);
    expect(screen.getByText("class A")).toBeInTheDocument();
    expect(screen.getByText("Not used for priority")).toBeInTheDocument();
    expect(screen.getByText(/Found in the report text/)).toBeInTheDocument();
    expect(screen.getByText(/it is not used for priority until a reviewer verifies it/)).toBeInTheDocument();
    expect(screen.getByText("Urgent review requested")).toBeInTheDocument();
    expect(screen.getByText(/This is a flag, not a verified priority/)).toBeInTheDocument();
  });

  it("explains a candidate with no source instead of inventing evidence", async () => {
    const noSource = candidate({ provenance: { source_type: "llm_proposal", source_available: false, source_missing_reason: "the value was proposed by the model and has no supporting span in the report", extraction_origin: "llm_proposed_value" } });
    const { session } = setup("maintenance_supervisor", inc({ measurements: [noSource] }));
    render(<IncidentsPage session={session} />);
    expect(await screen.findByText(/Source not available: the value was proposed by the model/)).toBeInTheDocument();
    expect(screen.getByText(/do not approve without another source/)).toBeInTheDocument();
    expect(screen.queryByText(/Reported text:/)).toBeNull();
  });

  it.each([["support_engineer"], ["read_only_auditor"]])("%s sees no verification controls and the reason", async (role) => {
    const { session } = setup(role);
    render(<IncidentsPage session={session} />);
    expect(await screen.findByText(/Only supervisors and tenant administrators can verify measurements/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Verify measurement/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Reject measurement/ })).toBeNull();
  });

  it("requires a written justification before the confirmation dialog", async () => {
    const { api, session } = setup("maintenance_supervisor");
    render(<IncidentsPage session={session} />);
    await userEvent.click(await screen.findByRole("button", { name: "Verify measurement…" }));
    expect(await screen.findByText(/Write a justification of 10 to 500 characters/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.posts()).toHaveLength(0);
  });

  it("verifies with the guard of the displayed state, then shows the server's status, priority, decision and refreshed audit history", async () => {
    const { api, state, session } = setup("maintenance_supervisor", inc(), {
      [`POST ${verifyPath}`]: () => {
        state.incident = inc({ priority: "P2", measurements: [verified("P3", "P2")], notes: ["Measurement vibration_mm_s verified by a reviewer."] });
        state.events = [extractedEvent, { id: 9, action: "measurement.verified", actor: "supervisor@acme.test", actor_type: "user", details: { measurement: "vibration_mm_s", from: "UNVERIFIED", to: "HUMAN_VERIFIED", comment: "Checked the printout." }, created_at: "2026-01-01T11:00:00Z" }];
        return state.incident;
      },
    });
    render(<IncidentsPage session={session} />);
    await fill("Checked the maintenance printout.");
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    await waitFor(() => expect(api.posts()).toHaveLength(1));
    expect(api.posts()[0]).toMatchObject({ path: verifyPath, body: { decision: "approve", comment: "Checked the maintenance printout.", expected_trust_status: "UNVERIFIED" } });
    expect(Object.keys(api.posts()[0].body as object).sort()).toEqual(["comment", "decision", "expected_trust_status"]);
    expect(await screen.findByText("Human-verified")).toBeInTheDocument();
    expect(screen.getByText("Used for priority")).toBeInTheDocument();
    expect(screen.getByText(/Measurement verified. The server recalculated the incident priority: P3 → P2/)).toBeInTheDocument();
    expect(await screen.findByText(/Priority P3 → P2 \(rule: numeric_rule\)/)).toBeInTheDocument();
    expect(screen.getByText("#77")).toBeInTheDocument();
    expect((await screen.findAllByText("Measurement verified by a human reviewer")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Verify measurement…" })).toBeNull();
    expect(api.calls.filter((c) => c.path === `/incidents/${ID}/history`).length).toBeGreaterThan(1);
  });

  it("shows the priority the server returns, including no change (nothing is hardcoded)", async () => {
    const { state, session } = setup("tenant_admin", inc({ priority: "P1", measurements: [submitted()] }), {
      [`POST ${verifyPath}`]: () => { state.incident = inc({ priority: "P1", measurements: [verified("P1", "P1", "numeric_rule_no_change")] }); return state.incident; },
    });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    expect(await screen.findByText(/Priority P1 → P1 \(rule: numeric_rule_no_change\)/)).toBeInTheDocument();
    expect(screen.queryByText(/→ P2/)).toBeNull();
  });

  it("uses VALIDATED as the guard for a submitted observation", async () => {
    const { api, state, session } = setup("maintenance_supervisor", inc({ measurements: [submitted()] }), {
      [`POST ${verifyPath}`]: () => { state.incident = inc({ measurements: [verified()] }); return state.incident; },
    });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    await waitFor(() => expect(api.posts()[0].body).toMatchObject({ expected_trust_status: "VALIDATED" }));
  });

  it("rejects a measurement and shows it excluded from priority", async () => {
    const rejected = candidate({ status: "rejected", verification_status: "rejected", trust_status: "REJECTED", verification: { decision: "reject", transition: "UNVERIFIED->REJECTED", reviewer_id: "u-2", reviewed_at: "2026-01-01T11:00:00Z", comment: "Does not match the printout.", priority_before: "P3", priority_after: "P3", applied_rule: "none" } });
    const { api, state, session } = setup("maintenance_supervisor", inc(), {
      [`POST ${verifyPath}`]: () => { state.incident = inc({ measurements: [rejected] }); return state.incident; },
    });
    render(<IncidentsPage session={session} />);
    await fill("Does not match the printout.");
    await userEvent.click(screen.getByRole("button", { name: "Reject measurement…" }));
    expect(within(screen.getByRole("alertdialog")).getByText(/stays excluded from the priority calculation/)).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Reject measurement" }));
    await waitFor(() => expect(api.posts()[0].body).toMatchObject({ decision: "reject", expected_trust_status: "UNVERIFIED" }));
    expect(await screen.findByText("Rejected by reviewer")).toBeInTheDocument();
    expect(screen.getByText(/It stays excluded from the priority calculation/)).toBeInTheDocument();
    expect(screen.getByText("Not used for priority")).toBeInTheDocument();
  });

  it("hides the controls for the incident's creator and explains why (the server still enforces it)", async () => {
    const { session } = setup("maintenance_supervisor", inc(), {}, { email: CREATOR });
    render(<IncidentsPage session={session} />);
    expect(await screen.findByText(/You created this incident, so a different reviewer must verify/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify measurement…" })).toBeNull();
  });

  it("shows the server's separation-of-duties refusal when the creator is not visible in history", async () => {
    const { session } = setup("maintenance_supervisor", inc(), { [`POST ${verifyPath}`]: () => errorResponse(403, "separation_of_duties", "The person who created the incident cannot verify its measurements") });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    expect(await screen.findByText(/You created this incident, so you cannot verify its measurements/)).toBeInTheDocument();
    expect(screen.getByText("Unverified candidate")).toBeInTheDocument();
  });

  it("shows a role refusal from the server even if the client believed the action was allowed", async () => {
    const { session } = setup("maintenance_supervisor", inc(), { [`POST ${verifyPath}`]: () => errorResponse(403, "insufficient_role", "Role 'x' lacks permission 'incidents:review'") });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    expect(await screen.findByText(/The server refused this action for your role/)).toBeInTheDocument();
  });

  it("reports an incident that is not in the tenant (cross-tenant ids look like 404)", async () => {
    const { session } = setup("maintenance_supervisor", inc(), { [`POST ${verifyPath}`]: () => errorResponse(404, "not_found", "Incident not found") });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    expect(await screen.findByText("This incident was not found in your tenant.")).toBeInTheDocument();
  });

  it("handles a stale or duplicate decision (409) by saying so and reloading the latest state", async () => {
    const { api, state, session } = setup("maintenance_supervisor", inc(), {
      [`POST ${verifyPath}`]: () => { state.incident = inc({ priority: "P2", measurements: [verified()] }); return errorResponse(409, "measurement_not_pending", "No pending candidate measurement with that name (already HUMAN_VERIFIED)"); },
    });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    expect(await screen.findByText(/already HUMAN_VERIFIED\)\. Someone else may already have decided/)).toBeInTheDocument();
    expect(await screen.findByText("Human-verified")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "GET" && c.path === `/incidents/${ID}`).length).toBeGreaterThan(1);
  });

  it("handles a 422 and a network error without changing the displayed state", async () => {
    let mode: "422" | "net" = "422";
    const { session } = setup("maintenance_supervisor", inc(), { [`POST ${verifyPath}`]: () => { if (mode === "net") throw new TypeError("failed to fetch"); return errorResponse(422, "validation_error", "Request validation failed"); } });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    expect(await screen.findByText(/The decision was not accepted: Request validation failed/)).toBeInTheDocument();
    mode = "net";
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" }));
    expect(await screen.findByText(/Cannot reach the server. Nothing was changed/)).toBeInTheDocument();
    expect(screen.getByText("Unverified candidate")).toBeInTheDocument();
  });

  it("sends one request when the confirmation is activated twice", async () => {
    let release: (v: unknown) => void = () => {};
    const gate = new Promise((r) => { release = r; });
    const { api, state, session } = setup("maintenance_supervisor", inc(), { [`POST ${verifyPath}`]: async () => { await gate; state.incident = inc({ measurements: [verified()] }); return state.incident; } });
    render(<IncidentsPage session={session} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Verify measurement…" }));
    const confirm = within(screen.getByRole("alertdialog")).getByRole("button", { name: "Verify measurement" });
    await userEvent.dblClick(confirm);
    release(null);
    await waitFor(() => expect(screen.getByText("Human-verified")).toBeInTheDocument());
    expect(api.posts()).toHaveLength(1);
  });

  it("states when there are no measurements and when the state cannot be decided", async () => {
    const { session } = setup("maintenance_supervisor", inc({ measurements: [] }));
    const { unmount } = render(<IncidentsPage session={session} />);
    expect(await screen.findByText("No numeric measurements were recorded for this incident.")).toBeInTheDocument();
    unmount();
    const other = setup("maintenance_supervisor", inc({ measurements: [candidate({ trust_status: "SUBMITTED", status: "submitted" })] }));
    render(<IncidentsPage session={other.session} />);
    expect(await screen.findByText(/cannot be decided from here/)).toBeInTheDocument();
  });

  it("shows loading before the incident arrives", async () => {
    const { session } = setup("maintenance_supervisor");
    render(<IncidentsPage session={session} />);
    expect(screen.queryByText("Numeric measurements")).toBeNull();
    expect(await screen.findByText("Numeric measurements")).toBeInTheDocument();
  });
});
