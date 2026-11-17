import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import { APEX, MERIDIAN, apiToken, asUser, auth, confirmDialog, go } from "./helpers";

/**
 * Batch 5 browser acceptance, LIVE: the real React build served with the real API, worker, PostgreSQL (isolated database eaop_e2e) and mock services started by
 * scripts/e2e_stack.py. Nothing is mocked. Set-up uses the public API only for reading results and for actions the test deliberately performs outside the UI.
 */
const SHOTS = "../evaluation/ui-acceptance/batch5";
const REPORT = "Pump P-101 shows abnormal vibration at the drive end, with a grinding noise since this morning.";
const NAME = "vibration_mm_s";

async function submitWithObservation(page: Page, value = "8.4", source = "gauge GA-7"): Promise<void> {
  await go(page, "#/incidents", "Incident Explorer");
  await page.getByLabel("Fault report").fill(REPORT);
  await page.getByRole("button", { name: "Add a structured observation" }).click();
  await page.getByLabel("Asset", { exact: true }).fill("P-101");
  await page.getByLabel("Value").fill(value);
  await page.getByLabel(/Source reference/).fill(source);
  await page.getByRole("button", { name: "Analyse report" }).click();
  await expect(page.getByRole("heading", { level: 3, name: /·/ }).first()).toBeVisible();
  await expect(page.locator(`[data-measurement="${NAME}"]`)).toBeVisible();
}

async function latestIncident(request: APIRequestContext, tenant: string, role: "engineer" | "supervisor" | "admin" | "auditor") {
  const res = await request.get("/api/v1/incidents?limit=1&sort=created_at&order=desc", { headers: auth(await apiToken(request, tenant, role)) });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).items[0] as { id: string; priority: string; measurements: { name: string; trust_status: string }[] };
}

const verifyUrl = (id: string) => `/api/v1/incidents/${id}/measurements/${NAME}/verify`;
const decision = { decision: "approve", comment: "Checked the maintenance printout.", expected_trust_status: "VALIDATED" };

test.describe("structured observation and human verification through the real UI", () => {
  test("engineer submits an observation, it stays unverified, a supervisor verifies it, the server priority is shown, others are refused", async ({ browser, request }) => {
    const eng = await asUser(browser, APEX, "engineer");
    await submitWithObservation(eng.page);
    const card = eng.page.locator(`[data-measurement="${NAME}"]`);
    await expect(card).toHaveAttribute("data-trust", "VALIDATED");
    await expect(card.getByText("Submitted · awaiting verification")).toBeVisible();
    await expect(card.getByText("Not used for priority")).toBeVisible();
    await expect(card.getByText(/Structured observation submitted by “gauge GA-7”/)).toBeVisible();
    await expect(eng.page.getByText("Human-verified")).toHaveCount(0);
    await expect(eng.page.getByText(/Only supervisors and tenant administrators can verify measurements/)).toBeVisible();
    await expect(eng.page.getByRole("button", { name: "Verify measurement…" })).toHaveCount(0);
    await eng.page.screenshot({ path: `${SHOTS}/01-engineer-submitted-awaiting-verification.png`, fullPage: true });

    const created = await latestIncident(request, APEX, "engineer");
    expect(created.measurements.find((m) => m.name === NAME)?.trust_status).toBe("VALIDATED");
    const before = created.priority;

    // Backend authority: an engineer and an auditor are refused by the API itself, whatever the UI shows.
    for (const role of ["engineer", "auditor"] as const) {
      const refused = await request.post(verifyUrl(created.id), { headers: auth(await apiToken(request, APEX, role)), data: decision });
      expect(refused.status(), role).toBe(403);
      expect((await refused.json()).error.code).toBe("insufficient_role");
    }
    // Cross-tenant: another tenant's supervisor cannot see or verify it.
    const foreign = await request.post(verifyUrl(created.id), { headers: auth(await apiToken(request, MERIDIAN, "supervisor")), data: decision });
    expect(foreign.status()).toBe(404);

    const sup = await asUser(browser, APEX, "supervisor");
    await sup.page.evaluate((id) => { window.location.hash = `#/incidents?id=${id}`; }, created.id);
    await sup.page.reload();
    const supCard = sup.page.locator(`[data-measurement="${NAME}"]`);
    await expect(supCard.getByText("Submitted · awaiting verification")).toBeVisible();
    await sup.page.getByLabel(/Justification for vibration/).fill("Checked the maintenance printout.");
    await sup.page.getByRole("button", { name: "Verify measurement…" }).click();
    await sup.page.screenshot({ path: `${SHOTS}/02-supervisor-confirmation-dialog.png` });
    await confirmDialog(sup.page, "Verify measurement");

    await expect(supCard.getByText("Human-verified")).toBeVisible();
    await expect(supCard).toHaveAttribute("data-trust", "HUMAN_VERIFIED");
    await expect(supCard.getByText("Used for priority")).toBeVisible();
    const after = await latestIncident(request, APEX, "supervisor");
    expect(after.id).toBe(created.id);
    expect(after.measurements.find((m) => m.name === NAME)?.trust_status).toBe("HUMAN_VERIFIED");
    // The page shows exactly what the server decided (never a value computed in the browser).
    await expect(sup.page.getByText(new RegExp(`Priority ${before} → ${after.priority} \\(rule: [a-z_]+\\)`))).toBeVisible();
    await expect(sup.page.locator("article.card").getByText(after.priority, { exact: true }).first()).toBeVisible();
    await expect(sup.page.getByText("Measurement verified by a human reviewer").first()).toBeVisible();
    await expect(sup.page.getByText(/Audit event|recorded in the audit history below/)).toBeVisible();
    await sup.page.screenshot({ path: `${SHOTS}/03-supervisor-verified-priority-from-server.png`, fullPage: true });

    // Duplicate / stale decision: the server refuses and the data does not change.
    const again = await request.post(verifyUrl(created.id), { headers: auth(await apiToken(request, APEX, "supervisor")), data: decision });
    expect(again.status()).toBe(409);
    expect((await (await request.get(`/api/v1/incidents/${created.id}`, { headers: auth(await apiToken(request, APEX, "supervisor")) })).json()).priority).toBe(after.priority);

    // The audit trail is visible to an auditor in the UI.
    const aud = await asUser(browser, APEX, "auditor");
    await go(aud.page, "#/audit", "Audit Logs");
    await aud.page.getByLabel("Entity id").fill(created.id);
    await expect(aud.page.getByText("measurement.verified", { exact: true })).toBeVisible();
    await Promise.all([eng.context.close(), sup.context.close(), aud.context.close()]);
  });

  test("a supervisor can reject a measurement and it stays excluded from priority", async ({ browser, request }) => {
    const eng = await asUser(browser, APEX, "engineer");
    await submitWithObservation(eng.page, "9.9", "unreadable photo");
    const created = await latestIncident(request, APEX, "engineer");
    const before = created.priority;
    const sup = await asUser(browser, APEX, "supervisor");
    await sup.page.evaluate((id) => { window.location.hash = `#/incidents?id=${id}`; }, created.id);
    await sup.page.reload();
    await sup.page.getByLabel(/Justification for vibration/).fill("Does not match the printout.");
    await sup.page.getByRole("button", { name: "Reject measurement…" }).click();
    await confirmDialog(sup.page, "Reject measurement");
    const card = sup.page.locator(`[data-measurement="${NAME}"]`);
    await expect(card.getByText("Rejected by reviewer")).toBeVisible();
    await expect(card.getByText("Not used for priority")).toBeVisible();
    expect((await latestIncident(request, APEX, "supervisor")).priority).toBe(before);
    await sup.page.screenshot({ path: `${SHOTS}/04-supervisor-rejected.png`, fullPage: true });
    await Promise.all([eng.context.close(), sup.context.close()]);
  });

  test("separation of duties: a supervisor who created the incident cannot verify its measurement, in the UI or the API", async ({ browser, request }) => {
    const sup = await asUser(browser, APEX, "supervisor");
    await submitWithObservation(sup.page, "7.7", "gauge GA-9");
    await expect(sup.page.getByText(/You created this incident, so a different reviewer must verify/)).toBeVisible();
    await expect(sup.page.getByRole("button", { name: "Verify measurement…" })).toHaveCount(0);
    const mine = await latestIncident(request, APEX, "supervisor");
    const refused = await request.post(verifyUrl(mine.id), { headers: auth(await apiToken(request, APEX, "supervisor")), data: decision });
    expect(refused.status()).toBe(403);
    expect((await refused.json()).error.code).toBe("separation_of_duties");
    await sup.page.screenshot({ path: `${SHOTS}/05-creator-cannot-verify.png`, fullPage: true });
    await sup.context.close();
  });

  test("the form refuses a comma decimal before calling the server", async ({ browser }) => {
    const eng = await asUser(browser, APEX, "engineer");
    await go(eng.page, "#/incidents", "Incident Explorer");
    await eng.page.getByLabel("Fault report").fill(REPORT);
    await eng.page.getByRole("button", { name: "Add a structured observation" }).click();
    await eng.page.getByLabel("Asset", { exact: true }).fill("P-101");
    await eng.page.getByLabel("Value").fill("8,4");
    await eng.page.getByRole("button", { name: "Analyse report" }).click();
    await expect(eng.page.getByText("Use a decimal point, not a comma (for example 8.4).")).toBeVisible();
    await eng.context.close();
  });
});
