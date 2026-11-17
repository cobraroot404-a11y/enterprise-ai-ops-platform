import { expect, test } from "@playwright/test";
import { APEX, MERIDIAN, PASSWORD, asUser, emailFor, go, signIn } from "./helpers";
import type { Role } from "./helpers";

test.describe("authentication and session", () => {
  test("validates the form, rejects bad credentials, signs in and out", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Enter a valid email address.")).toBeVisible();
    await expect(page.getByText("Enter your password.")).toBeVisible();

    await page.getByLabel("Tenant").fill(APEX);
    await page.getByLabel("Email").fill(emailFor(APEX, "engineer"));
    await page.getByLabel("Password").fill("wrong-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toContainText("Invalid credentials");

    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByLabel("Signed in as")).toContainText(APEX);
    await expect(page.getByLabel("Signed in as")).toContainText("Support engineer");
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  });

  test("returns to sign-in with an explanation when the server rejects the session", async ({ page }) => {
    await signIn(page, APEX, "engineer");
    await page.route("**/api/v1/metrics", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { code: "token_expired", message: "Token expired" } }) }));
    await page.reload();
    await expect(page.getByText(/session expired or was rejected/i)).toBeVisible();
    await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  });

  test("a signed-in session survives a reload but not a new browser context", async ({ page, browser }) => {
    await signIn(page, APEX, "auditor");
    await page.reload();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    const other = await browser.newContext();
    const fresh = await other.newPage();
    await fresh.goto("/");
    await expect(fresh.getByRole("form", { name: "Sign in" })).toBeVisible();
    await other.close();
  });
});

const EXPECTED: Record<Role, { count: number; has: string[]; lacks: string[] }> = {
  admin: { count: 13, has: ["Audit Logs", "Administration"], lacks: [] },
  supervisor: { count: 11, has: ["Approval Queue"], lacks: ["Audit Logs", "Administration"] },
  engineer: { count: 11, has: ["Incident Explorer"], lacks: ["Audit Logs", "Administration"] },
  auditor: { count: 12, has: ["Audit Logs"], lacks: ["Administration"] },
};

test.describe("role-based navigation (both tenants share one application)", () => {
  for (const tenant of [APEX, MERIDIAN]) {
    for (const role of Object.keys(EXPECTED) as Role[]) {
      test(`${tenant} ${role}`, async ({ browser }) => {
        const { page, context } = await asUser(browser, tenant, role);
        const links = page.getByRole("navigation", { name: "Main" }).getByRole("link");
        await expect(links).toHaveCount(EXPECTED[role].count);
        for (const name of EXPECTED[role].has) await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name })).toBeVisible();
        for (const name of EXPECTED[role].lacks) await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name })).toHaveCount(0);
        await context.close();
      });
    }
  }

  test("a page hidden by role explains itself when opened directly (the server enforces access)", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await page.evaluate(() => { window.location.hash = "#/audit"; });
    await expect(page.getByRole("heading", { name: "Not available for your role" })).toBeVisible();
    const res = await page.request.get("/api/v1/audit", { headers: { Authorization: `Bearer ${JSON.parse(await page.evaluate(() => sessionStorage.getItem("eaop.session") ?? "{}")).token}` } });
    expect(res.status()).toBe(403);
    await context.close();
  });

  test("platform administrators see only Administration and can create a tenant", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Email").fill("platform@e2e.example.test");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    const links = page.getByRole("navigation", { name: "Main" }).getByRole("link");
    await expect(links).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 2, name: "Administration" })).toBeVisible();
    const slug = `new-${Date.now().toString(36)}`;
    await page.getByLabel("Tenant name (slug)").fill(slug);
    await page.getByLabel("Display name").fill("New customer (fictional)");
    await page.getByRole("button", { name: "Review and create…" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Create tenant" }).click();
    await expect(page.getByText(`Tenant ${slug} created`)).toBeVisible();
    await expect(page.getByText("platform.login").first()).toBeVisible();
  });
});

test("all 13 pages render against the real backend without console errors", async ({ browser }) => {
  const { page, context } = await asUser(browser, MERIDIAN, "admin");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("favicon")) errors.push(m.text()); });
  const pages: [string, string][] = [
    ["#/overview", "Overview"], ["#/onboarding", "Customer Onboarding"], ["#/data-sources", "Data Sources"], ["#/documents", "Document Library"],
    ["#/assistant", "AI Knowledge Assistant"], ["#/incidents", "Incident Explorer"], ["#/tickets", "Support Tickets"], ["#/approvals", "Approval Queue"],
    ["#/workflows", "Workflow History"], ["#/integrations", "Integration Health"], ["#/evaluation", "Evaluation Dashboard"], ["#/audit", "Audit Logs"],
    ["#/administration", "Administration"],
  ];
  for (const [hash, heading] of pages) {
    await go(page, hash, heading);
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByText(/Could not load/)).toHaveCount(0);
  }
  expect(errors).toEqual([]);
  await context.close();
});
