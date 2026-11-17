import { expect, test } from "@playwright/test";
import { APEX, APEX_REPORT, MERIDIAN, MERIDIAN_REPORT, analyse, approve, apiToken, approvedApexTicket, asUser, auth, confirmDialog, draftAndRequestApproval, go, injectFailure, mockState, openTicket } from "./helpers";

test.describe("Apex: incident to submitted ticket through the real application", () => {
  test("report, draft, separate approval, worker submission and audit trail", async ({ browser, request }) => {
    const before = await mockState(request, "ticketing");
    const eng = await asUser(browser, APEX, "engineer");
    await analyse(eng.page, APEX_REPORT);
    await expect(eng.page.getByText("Evidence verified · ready for a ticket").first()).toBeVisible();
    await expect(eng.page.getByText("equipment verified in register")).toBeVisible();
    await expect(eng.page.getByText("AI-generated").first()).toBeVisible();
    await expect(eng.page.getByText("Retrieved evidence").first()).toBeVisible();
    const id = await draftAndRequestApproval(eng.page);

    // The author cannot approve their own ticket.
    await go(eng.page, "#/approvals", "Approval Queue");
    await expect(eng.page.getByText(/you cannot decide on it/i).first()).toBeVisible();
    await expect(eng.page.getByRole("button", { name: "Approve…" })).toHaveCount(0);

    const sup = await asUser(browser, APEX, "supervisor");
    await approve(sup.page, id);
    await expect(sup.page.getByText(/only when the external system confirms/)).toBeVisible();

    await openTicket(eng.page, id);
    await expect(eng.page.getByText(/Confirmed by the external system/)).toContainText("MNT-");
    await expect(eng.page.getByText("Approval decisions")).toBeVisible();
    await expect(eng.page.getByText("approval.approved").or(eng.page.getByText("Approval decision: approved"))).toBeVisible();

    const after = await mockState(request, "ticketing");
    expect(after.count).toBe(before.count + 1);

    const aud = await asUser(browser, APEX, "auditor");
    await go(aud.page, "#/audit", "Audit Logs");
    await aud.page.getByLabel("Entity id").fill(id);
    for (const action of ["ticket.drafted", "approval.approved", "ticket.submitted"]) await expect(aud.page.getByText(action, { exact: true })).toBeVisible();
    await Promise.all([eng.context.close(), sup.context.close(), aud.context.close()]);
  });

  test("workflow history and overview reflect the real submission", async ({ browser, request }) => {
    await approvedApexTicket(request, "Pump P-102 shows abnormal vibration at 6.0 mm/s, grinding noise.");
    const { page, context } = await asUser(browser, APEX, "supervisor");
    await go(page, "#/workflows", "Workflow History");
    await expect(page.locator(".badge", { hasText: /^Completed$/ }).first()).toBeVisible({ timeout: 20_000 });
    await go(page, "#/overview", "Overview");
    await expect(page.getByRole("listitem").filter({ hasText: "Submitted tickets" })).toBeVisible();
    await context.close();
  });
});

test.describe("human-review gate in the UI", () => {
  test("an unregistered asset is blocked, needs a justified human review, and still cannot be released", async ({ browser }) => {
    const eng = await asUser(browser, APEX, "engineer");
    await analyse(eng.page, "Pump Z-999 shows abnormal vibration at 8.4 mm/s with a grinding noise.");
    await expect(eng.page.getByText("Blocked · human review required").first()).toBeVisible();
    await expect(eng.page.getByText("equipment NOT in register")).toBeVisible();
    await expect(eng.page.getByText(/Only supervisors and tenant administrators can review/)).toBeVisible();
    await expect(eng.page.getByRole("button", { name: /Create ticket draft/ })).toHaveCount(0);

    const sup = await asUser(browser, APEX, "supervisor");
    await analyse(sup.page, "Pump Z-998 shows abnormal vibration at 8.4 mm/s with a grinding noise.");
    await sup.page.getByRole("button", { name: "Accept for ticketing…" }).click();
    await expect(sup.page.getByText(/Write a justification/)).toBeVisible();
    await sup.page.getByLabel(/Justification/).fill("Z-998 is a newly installed pump, verified on site.");
    await sup.page.getByRole("button", { name: "Accept for ticketing…" }).click();
    await expect(sup.page.getByRole("alertdialog")).toContainText("does not make unsupported AI statements true");
    await confirmDialog(sup.page, "Accept incident");
    await expect(sup.page.getByText("Human-reviewed · accepted").first()).toBeVisible();
    await expect(sup.page.getByText(/cannot be approved or sent until the equipment is registered/)).toBeVisible();
    const id = await draftAndRequestApproval(sup.page);

    const admin = await asUser(browser, APEX, "admin");
    await go(admin.page, "#/approvals", "Approval Queue");
    const card = admin.page.locator(`article[data-ticket-id="${id}"]`);
    await expect(card.getByText(/asset NOT in register/)).toBeVisible();
    await card.getByRole("button", { name: "Approve…" }).click();
    await confirmDialog(admin.page, "Approve");
    await expect(admin.page.getByText(/not in the tenant's authoritative register/)).toBeVisible();
    await expect(admin.page.getByText(/Approved\. The ticket is queued/)).toHaveCount(0);
    await openTicket(admin.page, id);
    await expect(admin.page.getByText("Awaiting approval").first()).toBeVisible();

    // A rejection is a recorded, final decision.
    await approve(admin.page, id, "Reject");
    await openTicket(admin.page, id);
    await expect(admin.page.locator(".badge", { hasText: /^Rejected$/ }).first()).toBeVisible();
    await Promise.all([eng.context.close(), sup.context.close(), admin.context.close()]);
  });

  test("a rejected incident can never become a ticket", async ({ browser }) => {
    const sup = await asUser(browser, APEX, "supervisor");
    await analyse(sup.page, "Pump Z-997 shows abnormal vibration at 8.4 mm/s with a grinding noise.");
    await sup.page.getByLabel(/Justification/).fill("Not a real asset in this plant.");
    await sup.page.getByRole("button", { name: "Reject…" }).click();
    await confirmDialog(sup.page, "Reject incident");
    await expect(sup.page.getByText(/can never become a ticket/).first()).toBeVisible();
    await expect(sup.page.getByRole("button", { name: /Create ticket draft/ })).toHaveCount(0);
    await sup.context.close();
  });
});

test.describe("submission failure and recovery", () => {
  test("a permanent failure is shown as failed, never as submitted, and a supervisor can retry", async ({ browser, request }) => {
    await injectFailure(request, "ticketing", "400", 1);
    const { ticketId } = await approvedApexTicket(request, "Pump P-103 shows abnormal vibration at 7.5 mm/s with a grinding noise.");
    const sup = await asUser(browser, APEX, "supervisor");
    await openTicket(sup.page, ticketId);
    await expect(sup.page.getByText(/Submission failed after 1 attempt/)).toBeVisible({ timeout: 25_000 });
    await expect(sup.page.getByText(/Confirmed by the external system/)).toHaveCount(0);
    await sup.page.getByRole("button", { name: "Retry submission…" }).click();
    await confirmDialog(sup.page, "Retry");
    await expect(sup.page.getByText(/Confirmed by the external system/)).toContainText("MNT-", { timeout: 30_000 });
    const eng = await asUser(browser, APEX, "engineer");
    await openTicket(eng.page, ticketId);
    await expect(eng.page.getByRole("button", { name: /Retry submission/ })).toHaveCount(0);
    await Promise.all([sup.context.close(), eng.context.close()]);
  });

  test("a transient outage is retried automatically and ends submitted exactly once", async ({ browser, request }) => {
    const before = await mockState(request, "ticketing");
    await injectFailure(request, "ticketing", "503", 1);
    const { ticketId } = await approvedApexTicket(request, "Pump P-101 shows abnormal vibration at 5.5 mm/s with a grinding noise.");
    const { page, context } = await asUser(browser, APEX, "supervisor");
    await openTicket(page, ticketId);
    await expect(page.getByText(/Confirmed by the external system/)).toContainText("MNT-", { timeout: 40_000 });
    const after = await mockState(request, "ticketing");
    expect(after.count).toBe(before.count + 1);
    await context.close();
  });
});

test.describe("Meridian: the same application, driven by its own configuration", () => {
  test("report, review if required, approval and submission to Meridian's service desk only", async ({ browser, request }) => {
    const apexBefore = await mockState(request, "ticketing");
    const deskBefore = await mockState(request, "servicedesk");
    const eng = await asUser(browser, MERIDIAN, "engineer");
    await go(eng.page, "#/incidents", "Incident Explorer");
    await expect(eng.page.getByLabel("Fault report")).toHaveAttribute("placeholder", /vehicle ID/);
    await analyse(eng.page, MERIDIAN_REPORT);
    await expect(eng.page.getByText("vehicle verified in register")).toBeVisible();
    await expect(eng.page.getByText(/Vehicle VH-2101: odometer 182450 km/)).toBeVisible();
    await expect(eng.page.getByText(/Harbor Fresh Foods/)).toBeVisible();
    const blocked = await eng.page.getByText("Blocked · human review required").first().isVisible();
    let ticketCreator = eng;
    if (blocked) {
      const sup0 = await asUser(browser, MERIDIAN, "supervisor");
      await analyse(sup0.page, MERIDIAN_REPORT);
      await sup0.page.getByLabel(/Justification/).fill("Reviewed against the maintenance manual by the supervisor.");
      await sup0.page.getByRole("button", { name: "Accept for ticketing…" }).click();
      await confirmDialog(sup0.page, "Accept incident");
      await expect(sup0.page.getByText("Human-reviewed · accepted").first()).toBeVisible();
      ticketCreator = sup0;
    }
    const id = await draftAndRequestApproval(ticketCreator.page);
    const approver = await asUser(browser, MERIDIAN, ticketCreator === eng ? "supervisor" : "admin");
    await approve(approver.page, id);
    await openTicket(approver.page, id);
    await expect(approver.page.getByText(/Confirmed by the external system/)).toContainText("WO-", { timeout: 30_000 });
    await expect(approver.page.getByText("Customer account Harbor Fresh Foods", { exact: false })).toBeVisible();
    expect((await mockState(request, "servicedesk")).count).toBe(deskBefore.count + 1);
    expect((await mockState(request, "ticketing")).count).toBe(apexBefore.count); // Apex's system was not touched
    await Promise.all([eng.context.close(), approver.context.close()]);
  });

  test("tenant-specific vocabulary comes from configuration and the server", async ({ browser }) => {
    const m = await asUser(browser, MERIDIAN, "engineer");
    await go(m.page, "#/assistant", "AI Knowledge Assistant");
    await expect(m.page.getByRole("textbox", { name: "Question" })).toHaveAttribute("placeholder", /vehicle problem/);
    await go(m.page, "#/documents", "Document Library");
    await expect(m.page.getByLabel("Kind").first()).toContainText("fleet_register");
    const a = await asUser(browser, APEX, "engineer");
    await go(a.page, "#/assistant", "AI Knowledge Assistant");
    await expect(a.page.getByRole("textbox", { name: "Question" })).toHaveAttribute("placeholder", /pump P-101/);
    await go(a.page, "#/documents", "Document Library");
    await expect(a.page.getByLabel("Kind").first()).not.toContainText("fleet_register");
    await Promise.all([m.context.close(), a.context.close()]);
  });
});

test.describe("tenant isolation", () => {
  test("each tenant sees only its own documents, incidents and tickets, and cannot reach the other's by id", async ({ browser, request }) => {
    const apexTok = auth(await apiToken(request, APEX, "admin"));
    const merTok = auth(await apiToken(request, MERIDIAN, "admin"));
    const { ticketId } = await approvedApexTicket(request);
    const merInc = await (await request.post("/api/v1/incidents/extract", { headers: auth(await apiToken(request, MERIDIAN, "engineer")), data: { report_text: MERIDIAN_REPORT } })).json();
    const merDocs = (await (await request.get("/api/v1/documents", { headers: merTok })).json()).items;
    const apexDocs = (await (await request.get("/api/v1/documents", { headers: apexTok })).json()).items;
    expect(merDocs.every((d: { filename: string }) => !d.filename.startsWith("apex") && d.filename !== "equipment_register.csv")).toBeTruthy();
    expect(apexDocs.every((d: { filename: string }) => !/meridian|fleet_|service_history|telematics/.test(d.filename))).toBeTruthy();
    expect((await request.get(`/api/v1/tickets/${ticketId}`, { headers: merTok })).status()).toBe(404);
    expect((await request.get(`/api/v1/incidents/${merInc.id}`, { headers: apexTok })).status()).toBe(404);
    expect((await request.get(`/api/v1/documents/${merDocs[0].id}`, { headers: apexTok })).status()).toBe(404);
    expect((await request.post(`/api/v1/approvals/${ticketId}/decision`, { headers: merTok, data: { decision: "approved" } })).status()).toBe(404);

    const m = await asUser(browser, MERIDIAN, "admin");
    await go(m.page, "#/tickets", "Support Tickets");
    await expect(m.page.getByText(/on P-101/)).toHaveCount(0);
    await go(m.page, "#/audit", "Audit Logs");
    await m.page.getByLabel("Entity id").fill(ticketId);
    await expect(m.page.getByText("No audit events match.")).toBeVisible();
    await m.context.close();
  });
});
