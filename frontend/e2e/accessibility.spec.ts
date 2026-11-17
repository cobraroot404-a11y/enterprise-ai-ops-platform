import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { APEX, MERIDIAN, PASSWORD, analyse, apiToken, asUser, auth, go } from "./helpers";

/**
 * Automated accessibility audit (axe-core, WCAG 2.0/2.1 A and AA rules plus best practices) across all 13 pages and the
 * representative states. Critical and serious violations fail the test. All findings, including moderate and minor ones, are
 * recorded in evaluation/reports/phase6-closure/axe-results.json. Passing axe does NOT establish WCAG conformance: automated
 * tools find only a subset of problems and this is not a screen-reader audit (see docs/phase6/phase6-closure-gate.md).
 */
const here = path.dirname(fileURLToPath(import.meta.url));
const chromeRun = process.env.E2E_BROWSER_CHANNEL === "chrome";
const resultsFile = path.resolve(here, "..", "..", "evaluation", "reports", "phase6-closure", chromeRun ? "axe-results-chrome.json" : "axe-results.json");
const findings: { state: string; url: string; violations: { id: string; impact: string | null | undefined; help: string; nodes: number }[]; passes: number }[] = [];

async function audit(page: Page, state: string): Promise<void> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]).analyze();
  findings.push({
    state, url: page.url().replace(/^https?:\/\/[^/]+/, ""), passes: result.passes.length,
    violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length })),
  });
  const blocking = result.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  expect(blocking.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`), `axe: ${state}`).toEqual([]);
}

test.afterAll(() => {
  fs.mkdirSync(path.dirname(resultsFile), { recursive: true });
  const prior = fs.existsSync(resultsFile) ? JSON.parse(fs.readFileSync(resultsFile, "utf-8")) : { audits: [] };
  const byState = new Map<string, unknown>(prior.audits.map((a: { state: string }) => [a.state, a]));
  for (const f of findings) byState.set(f.state, f);
  const audits = [...byState.values()] as typeof findings;
  const all = audits.flatMap((a) => a.violations);
  fs.writeFileSync(resultsFile, JSON.stringify({
    tool: "axe-core via @axe-core/playwright", tags: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"], browser: chromeRun ? "Google Chrome" : "Microsoft Edge",
    note: "Automated checks only. Not a WCAG conformance claim and not a screen-reader audit.",
    states_audited: audits.length, total_violations: all.length,
    by_impact: Object.fromEntries(["critical", "serious", "moderate", "minor"].map((i) => [i, all.filter((v) => v.impact === i).length])),
    audits,
  }, null, 1));
});

const PAGES: [string, string][] = [
  ["#/overview", "Overview"], ["#/onboarding", "Customer Onboarding"], ["#/data-sources", "Data Sources"], ["#/documents", "Document Library"],
  ["#/assistant", "AI Knowledge Assistant"], ["#/incidents", "Incident Explorer"], ["#/tickets", "Support Tickets"], ["#/approvals", "Approval Queue"],
  ["#/workflows", "Workflow History"], ["#/integrations", "Integration Health"], ["#/evaluation", "Evaluation Dashboard"], ["#/audit", "Audit Logs"],
  ["#/administration", "Administration"],
];

test("sign-in page: default, validation errors, expired-session notice", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  await audit(page, "login: default");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await audit(page, "login: validation errors");
  await page.getByLabel("Email").fill("a@b.co");
  await page.getByLabel("Password").fill("x");
  await page.route("**/api/v1/auth/login", (r) => r.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { code: "invalid_credentials", message: "Invalid credentials" } }) }));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Invalid credentials" })).toBeVisible();
  await audit(page, "login: server error");
});

test("all 13 pages, default rendering (tenant administrator, Meridian)", async ({ browser }) => {
  const { page, context } = await asUser(browser, MERIDIAN, "admin");
  for (const [hash, heading] of PAGES) {
    await go(page, hash, heading);
    await expect(page.getByText(/^Loading /)).toHaveCount(0, { timeout: 15_000 });
    await audit(page, `page: ${heading}`);
  }
  await context.close();
});

test("all pages as a read-only auditor and an engineer (reduced controls)", async ({ browser }) => {
  for (const role of ["auditor", "engineer"] as const) {
    const { page, context } = await asUser(browser, APEX, role);
    for (const [hash, heading] of PAGES.filter(([, h]) => ["Overview", "Document Library", "Incident Explorer", "Support Tickets", "Approval Queue"].includes(h))) {
      await go(page, hash, heading);
      await expect(page.getByText(/^Loading /)).toHaveCount(0, { timeout: 15_000 });
      await audit(page, `page as ${role}: ${heading}`);
    }
    await context.close();
  }
});

test("loading and empty states", async ({ browser }) => {
  const { page, context } = await asUser(browser, APEX, "engineer");
  await page.route("**/api/v1/tickets**", async (route) => { await new Promise((r) => setTimeout(r, 1500)); await route.continue(); }, { times: 1 });
  await page.evaluate(() => { window.location.hash = "#/tickets"; });
  await expect(page.getByText("Loading tickets…")).toBeVisible();
  await audit(page, "state: loading (tickets)");
  await expect(page.getByText("Loading tickets…")).toHaveCount(0, { timeout: 10_000 });
  await go(page, "#/documents", "Document Library");
  await page.getByLabel("Search file name").fill("zzz-nothing-matches");
  await expect(page.getByText("No documents match the filters.")).toBeVisible();
  await audit(page, "state: empty (documents filtered)");
  await go(page, "#/workflows", "Workflow History");
  await page.getByLabel("Ticket id").fill("not-a-uuid");
  await expect(page.getByText("Enter a full ticket id (UUID).")).toBeVisible();
  await audit(page, "state: form error (workflow filter)");
  await context.close();
});

test("forms with validation errors: documents, assistant, administration, data sources", async ({ browser }) => {
  const a = await asUser(browser, APEX, "engineer");
  await go(a.page, "#/documents", "Document Library");
  await a.page.getByLabel(/File \(PDF/).setInputFiles({ name: "bad.exe", mimeType: "application/octet-stream", buffer: Buffer.from("x") });
  await expect(a.page.getByText(/Unsupported file type/)).toBeVisible();
  await audit(a.page, "form: documents upload error");
  await go(a.page, "#/assistant", "AI Knowledge Assistant");
  await a.page.getByRole("textbox", { name: "Question" }).fill("hi");
  await a.page.getByRole("button", { name: "Ask" }).click();
  await expect(a.page.getByText("Enter a question of at least 3 characters.")).toBeVisible();
  await audit(a.page, "form: assistant question error");
  await go(a.page, "#/incidents", "Incident Explorer");
  await a.page.getByLabel("Fault report").fill("short");
  await a.page.getByRole("button", { name: "Analyse report" }).click();
  await expect(a.page.getByText(/at least 10 characters/)).toBeVisible();
  await audit(a.page, "form: incident report error");
  await a.context.close();

  const admin = await asUser(browser, APEX, "admin");
  await go(admin.page, "#/administration", "Administration");
  await admin.page.getByRole("button", { name: "Review and add…" }).click();
  await expect(admin.page.getByText("Enter a valid email address.")).toBeVisible();
  await audit(admin.page, "form: administration member errors");
  await go(admin.page, "#/data-sources", "Data Sources");
  const connectorForm = admin.page.getByRole("form", { name: "Add connector" });  // the page also holds the webhook endpoint form
  await connectorForm.getByRole("button", { name: "Review and add…" }).click();
  await expect(admin.page.getByText("Enter an http(s) URL.")).toBeVisible();
  await audit(admin.page, "form: connector configuration errors");
  const webhookForm = admin.page.getByRole("form", { name: "Add webhook endpoint" });
  await webhookForm.getByRole("button", { name: "Review and add…" }).click();
  await expect(webhookForm.getByText(/^Enter the NAME of a server environment variable/)).toBeVisible();
  await audit(admin.page, "form: webhook endpoint errors");
  await connectorForm.getByLabel("Name").fill("probe");
  await connectorForm.getByLabel("Base URL").fill("https://evil.example.org");
  await connectorForm.getByRole("button", { name: "Review and add…" }).click();
  await expect(admin.page.getByRole("alertdialog")).toBeVisible();
  await audit(admin.page, "dialog: connector confirmation");
  await admin.page.getByRole("alertdialog").getByRole("button", { name: "Add connector" }).click();
  await expect(admin.page.getByRole("alert").filter({ hasText: /not an approved|destination rejected/i })).toBeVisible();
  await audit(admin.page, "state: connector rejected by server");
  await admin.context.close();
});

test("incident review, citation inspection and ticket approval screens", async ({ browser, request }) => {
  const sup = await asUser(browser, APEX, "supervisor");
  await analyse(sup.page, "Pump Z-901 shows abnormal vibration at 8.4 mm/s with a grinding noise.");
  await expect(sup.page.getByText("This incident is blocked.")).toBeVisible();
  await audit(sup.page, "incident review: blocked incident with review controls");
  await sup.page.getByLabel(/Justification/).fill("Accessibility audit justification.");
  await sup.page.getByRole("button", { name: "Accept for ticketing…" }).click();
  await expect(sup.page.getByRole("alertdialog")).toBeVisible();
  await audit(sup.page, "dialog: incident review confirmation");
  await sup.page.keyboard.press("Escape");

  const eng = auth(await apiToken(request, APEX, "engineer"));
  const inc = await (await request.post("/api/v1/incidents/extract", { headers: eng, data: { report_text: "Pump P-101 shows abnormal vibration at 8.4 mm/s, grinding noise." } })).json();
  const t = await (await request.post("/api/v1/tickets", { headers: eng, data: { incident_id: inc.id } })).json();
  await request.post(`/api/v1/tickets/${t.id}/request-approval`, { headers: eng });
  await go(sup.page, "#/approvals", "Approval Queue");
  await expect(sup.page.getByRole("button", { name: "Approve…" }).first()).toBeVisible();
  await audit(sup.page, "ticket approval: queue card");
  await sup.page.getByRole("button", { name: "Approve…" }).first().click();
  await expect(sup.page.getByRole("alertdialog")).toBeVisible();
  await audit(sup.page, "dialog: approval confirmation");
  await sup.page.keyboard.press("Escape");
  await sup.page.getByRole("tab", { name: "Decided" }).click();
  await audit(sup.page, "approval queue: decided tab");

  await go(sup.page, "#/assistant", "AI Knowledge Assistant");
  await sup.page.getByRole("textbox", { name: "Question" }).fill("What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?");
  await sup.page.getByRole("button", { name: "Ask" }).click();
  await expect(sup.page.getByRole("heading", { name: "Supporting evidence" })).toBeVisible();
  await sup.page.getByRole("button", { name: "Inspect" }).first().click();
  await expect(sup.page.getByLabel(/Citation 1 details/)).toBeVisible();
  await audit(sup.page, "citation inspection: expanded");
  await request.post(`/api/v1/tickets/${t.id}/cancel`, { headers: eng }); // leave no pending approval behind for other specs
  await sup.context.close();
});

test("onboarding profile editor and integration health (administrator)", async ({ browser }) => {
  const { page, context } = await asUser(browser, MERIDIAN, "admin");
  await go(page, "#/onboarding", "Customer Onboarding");
  await page.getByLabel("Profile (JSON)").fill("{ broken");
  await page.getByRole("button", { name: "Validate and save…" }).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await audit(page, "form: profile JSON error");
  await context.close();
  expect(PASSWORD.length).toBeGreaterThan(8);
});
