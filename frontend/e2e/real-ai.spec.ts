import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { APEX, APEX_REPORT, MERIDIAN, MERIDIAN_REPORT, analyse, approve, asUser, confirmDialog, draftAndRequestApproval, go, mockState, openTicket } from "./helpers";
import type { Browser } from "@playwright/test";

/**
 * REAL-AI SMOKE TESTS (Ollama qwen2.5:1.5b + MiniLM). These exercise the actual model-backed application through the UI.
 * Real output varies, so assertions are invariants (labelling, gating, isolation, confirmed submission), not fixed answers
 * and not quality metrics. Run: E2E_REAL_AI=1 npx playwright test --project=real-ai
 */
test.describe.configure({ mode: "serial" });

async function pushThroughReview(browser: Browser, tenant: string, report: string, page: Page): Promise<{ id: string; reviewed: boolean }> {
  await analyse(page, report);
  const blocked = await page.getByText("Blocked · human review required").first().isVisible();
  if (!blocked) {
    const id = await draftAndRequestApproval(page);
    const sup = await asUser(browser, tenant, "supervisor");
    await approve(sup.page, id);
    await sup.context.close();
    return { id, reviewed: false };
  }
  const sup = await asUser(browser, tenant, "supervisor");
  await analyse(sup.page, report);
  await sup.page.getByLabel(/Justification/).fill("Reviewed by the supervisor because no verified evidence was produced.");
  await sup.page.getByRole("button", { name: "Accept for ticketing…" }).click();
  await confirmDialog(sup.page, "Accept incident");
  await expect(sup.page.getByText("Human-reviewed · accepted").first()).toBeVisible();
  const id = await draftAndRequestApproval(sup.page);
  const admin = await asUser(browser, tenant, "admin");
  await approve(admin.page, id);
  await Promise.all([sup.context.close(), admin.context.close()]);
  return { id, reviewed: true };
}

test("Apex through the UI with real inference: labelled answer or honest refusal, gated incident, confirmed submission", async ({ browser, request }) => {
  const eng = await asUser(browser, APEX, "engineer");
  await go(eng.page, "#/assistant", "AI Knowledge Assistant");
  await eng.page.getByRole("textbox", { name: "Question" }).fill("What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?");
  await eng.page.getByRole("button", { name: "Ask" }).click();
  const answer = eng.page.getByRole("article").first();
  await expect(answer.getByText(/AI-generated|Insufficient evidence|Answer withheld/).first()).toBeVisible();
  const grounded = await answer.getByText("AI-generated").isVisible();
  if (grounded) {
    await expect(answer.getByText("Verbatim quote verified").first()).toBeVisible();
    await expect(answer.getByText("Retrieved evidence").first()).toBeVisible();
  } else {
    await expect(answer.getByText("AI-generated")).toHaveCount(0); // never shows unverified model text
  }
  test.info().annotations.push({ type: "apex-question", description: grounded ? "grounded answer with verified citations" : "withheld or insufficient evidence" });

  const before = await mockState(request, "ticketing");
  const { id, reviewed } = await pushThroughReview(browser, APEX, APEX_REPORT, eng.page);
  test.info().annotations.push({ type: "apex-review", description: reviewed ? "human review was required" : "verified evidence, no review required" });
  await openTicket(eng.page, id);
  await expect(eng.page.getByText(/Confirmed by the external system/)).toContainText("MNT-", { timeout: 60_000 });
  expect((await mockState(request, "ticketing")).count).toBe(before.count + 1);
  await eng.context.close();
});

test("Meridian through the UI with real inference: profile extraction, enrichments, gating and its own service desk", async ({ browser, request }) => {
  const eng = await asUser(browser, MERIDIAN, "engineer");
  await go(eng.page, "#/assistant", "AI Knowledge Assistant");
  await eng.page.getByRole("textbox", { name: "Question" }).fill("What should I do when the service brake line pressure falls below 55 psi?");
  await eng.page.getByRole("button", { name: "Ask" }).click();
  const answer = eng.page.getByRole("article").first();
  await expect(answer.getByText(/AI-generated|Insufficient evidence|Answer withheld/).first()).toBeVisible();
  if (await answer.getByText("AI-generated").isVisible()) {
    for (const file of await answer.locator("strong").allTextContents()) expect(file).not.toMatch(/apex|equipment_register|incident_history/);
  }

  const desk = await mockState(request, "servicedesk");
  const apexBefore = await mockState(request, "ticketing");
  await analyse(eng.page, MERIDIAN_REPORT);
  await expect(eng.page.getByText("vehicle verified in register")).toBeVisible();
  await expect(eng.page.getByText(/Vehicle VH-2101: odometer/)).toBeVisible();
  await expect(eng.page.getByText(/Harbor Fresh Foods/)).toBeVisible();
  await expect(eng.page.getByText("AI-generated").first()).toBeVisible();
  const { id, reviewed } = await pushThroughReview(browser, MERIDIAN, MERIDIAN_REPORT, eng.page);
  test.info().annotations.push({ type: "meridian-review", description: reviewed ? "human review was required" : "verified evidence, no review required" });
  await openTicket(eng.page, id);
  await expect(eng.page.getByText(/Confirmed by the external system/)).toContainText("WO-", { timeout: 60_000 });
  expect((await mockState(request, "servicedesk")).count).toBe(desk.count + 1);
  expect((await mockState(request, "ticketing")).count).toBe(apexBefore.count);
  await eng.context.close();
});

test("real embeddings keep retrieval inside each tenant, in the UI", async ({ browser }) => {
  for (const [tenant, query, foreign] of [[APEX, "brake line pressure air dryer VH-2101", /meridian|fleet_|service_history|telematics/], [MERIDIAN, "pump bearing vibration drive end", /apex_|equipment_register|incident_history|maintenance_log/]] as const) {
    const { page, context } = await asUser(browser, tenant, "engineer");
    await go(page, "#/assistant", "AI Knowledge Assistant");
    await page.getByLabel(/Search evidence only/).check();
    await page.getByRole("textbox", { name: "Question" }).fill(query);
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText("Nothing here was written by a model.")).toBeVisible();
    const files = await page.locator(".hits li strong").allTextContents();
    expect(files.length).toBeGreaterThan(0);
    for (const f of files) expect(f).not.toMatch(foreign);
    await context.close();
  }
});
