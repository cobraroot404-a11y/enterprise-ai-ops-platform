import { expect } from "@playwright/test";
import type { APIRequestContext, Browser, BrowserContext, Page } from "@playwright/test";

export const PASSWORD = "E2e-Test-Passw0rd!"; // test-only credential of the isolated e2e stack (scripts/e2e_stack.py)
export const APEX = "apex-e2e";
export const MERIDIAN = "meridian-e2e";
export const MOCKS = { ticketing: "http://127.0.0.1:8211", servicedesk: "http://127.0.0.1:8215" };
const MOCK_KEYS = { ticketing: "e2e-ticketing-key", servicedesk: "e2e-servicedesk-key" };

export type Role = "admin" | "supervisor" | "engineer" | "auditor";
export const emailFor = (tenant: string, role: Role) => `${role}@${tenant}.example.test`;

export const APEX_REPORT = "Pump P-101 shows abnormal vibration at the drive end, measured at 8.4 mm/s, with a grinding noise.";
export const MERIDIAN_REPORT = "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle.";

export async function signIn(page: Page, tenant: string, role: Role): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Tenant").fill(tenant);
  await page.getByLabel("Email").fill(emailFor(tenant, role));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

/** A fresh browser context signed in as one user, so several people can act in one test. */
export async function asUser(browser: Browser, tenant: string, role: Role): Promise<{ page: Page; context: BrowserContext }> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signIn(page, tenant, role);
  return { page, context };
}

export async function go(page: Page, path: string, heading: string): Promise<void> {
  await page.evaluate((p) => { window.location.hash = p; }, path);
  await expect(page.getByRole("heading", { level: 2, name: heading })).toBeVisible();
}

export async function analyse(page: Page, report: string): Promise<void> {
  await go(page, "#/incidents", "Incident Explorer");
  await page.getByLabel("Fault report").fill(report);
  await page.getByRole("button", { name: "Analyse report" }).click();
  await expect(page.getByRole("heading", { level: 3, name: /·/ }).first()).toBeVisible();
}

export async function confirmDialog(page: Page, buttonName: string | RegExp): Promise<void> {
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: buttonName }).click();
  await expect(dialog).toBeHidden();
}

/** Draft a ticket from the incident currently selected on the Incident Explorer and request approval; returns the ticket id. */
export async function draftAndRequestApproval(page: Page): Promise<string> {
  await page.getByRole("button", { name: "Create ticket draft…" }).click();
  await confirmDialog(page, "Create draft");
  await expect(page.getByRole("heading", { level: 2, name: "Support Tickets" })).toBeVisible();
  await page.waitForURL(/#\/tickets\?id=/);
  const id = new URL(page.url()).hash.split("id=")[1];
  await page.getByRole("button", { name: "Request approval…" }).click();
  await confirmDialog(page, "Request approval");
  await expect(page.getByText("Awaiting approval").first()).toBeVisible();
  return id;
}

export async function approve(page: Page, ticketId: string, decision: "Approve" | "Reject" = "Approve"): Promise<void> {
  await go(page, "#/approvals", "Approval Queue");
  const card = page.locator(`article[data-ticket-id="${ticketId}"]`);
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: `${decision}…` }).click();
  await confirmDialog(page, decision);
}

export async function openTicket(page: Page, id: string): Promise<void> {
  await page.evaluate((i) => { window.location.hash = `#/tickets?id=${i}`; }, id);
  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: "Support Tickets" })).toBeVisible();
}

export async function apiToken(request: APIRequestContext, tenant: string, role: Role): Promise<string> {
  const res = await request.post("/api/v1/auth/login", { data: { email: emailFor(tenant, role), password: PASSWORD, tenant } });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).access_token as string;
}

export const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

export async function mockState(request: APIRequestContext, which: "ticketing" | "servicedesk"): Promise<{ count: number; requests: number }> {
  const res = await request.get(`${MOCKS[which]}/admin/state`, { headers: { "X-API-Key": MOCK_KEYS[which] } });
  const body = await res.json();
  return { count: which === "ticketing" ? body.ticket_count : body.count, requests: body.requests };
}

export async function injectFailure(request: APIRequestContext, which: "ticketing" | "servicedesk", mode: string, count = 1): Promise<void> {
  const res = await request.post(`${MOCKS[which]}/admin/failure`, { data: { mode, count }, headers: { "X-API-Key": MOCK_KEYS[which] } });
  expect(res.ok()).toBeTruthy();
}

/** Create an approved ticket for Apex entirely through the API (set-up only; the UI then verifies what happens next). */
export async function approvedApexTicket(request: APIRequestContext, report = APEX_REPORT): Promise<{ ticketId: string; title: string }> {
  const eng = auth(await apiToken(request, APEX, "engineer"));
  const sup = auth(await apiToken(request, APEX, "supervisor"));
  const inc = await (await request.post("/api/v1/incidents/extract", { headers: eng, data: { report_text: report } })).json();
  if (inc.review_status === "needs_review") {
    await request.post(`/api/v1/incidents/${inc.id}/review`, { headers: sup, data: { decision: "accept", comment: "Set-up review for an e2e test." } });
  }
  const t = await (await request.post("/api/v1/tickets", { headers: eng, data: { incident_id: inc.id } })).json();
  await request.post(`/api/v1/tickets/${t.id}/request-approval`, { headers: eng });
  const res = await request.post(`/api/v1/approvals/${t.id}/decision`, { headers: sup, data: { decision: "approved", comment: "e2e" } });
  expect(res.ok()).toBeTruthy();
  return { ticketId: t.id as string, title: t.title as string };
}
