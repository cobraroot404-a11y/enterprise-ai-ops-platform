import { expect, test } from "@playwright/test";
import { APEX, MERIDIAN, asUser, confirmDialog, go } from "./helpers";

test.describe("administration", () => {
  test("add a member, change a role with confirmation, remove a member; self-changes are blocked", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "admin");
    await go(page, "#/administration", "Administration");
    const email = `temp-${Date.now()}@apex-e2e.example.test`;
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Full name").fill("Temporary Tester");
    await page.getByLabel("Initial password").fill("short");
    await page.getByRole("button", { name: "Review and add…" }).click();
    await expect(page.getByText("Use at least 10 characters.")).toBeVisible();
    await page.getByLabel("Initial password").fill("A-long-enough-pw-1");
    await page.getByRole("button", { name: "Review and add…" }).click();
    await confirmDialog(page, "Add member");
    await expect(page.getByText(`${email} was added`)).toBeVisible();

    await page.getByLabel(`Role for ${email}`).selectOption("maintenance_supervisor");
    await expect(page.getByRole("alertdialog")).toContainText("Permissions change immediately");
    await confirmDialog(page, "Change role");
    await expect(page.getByText(`${email} is now Maintenance supervisor`)).toBeVisible();

    await expect(page.getByLabel(/Role for admin@apex-e2e/)).toBeDisabled();
    await page.getByRole("row").filter({ hasText: email }).getByRole("button", { name: "Remove…" }).click();
    await confirmDialog(page, "Remove");
    await expect(page.getByText(`${email} was removed`)).toBeVisible();
    await context.close();
  });
});

test.describe("data sources, onboarding and integration health", () => {
  test("a connector to an unauthorized destination is rejected by the server and nothing is saved", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "admin");
    await go(page, "#/data-sources", "Data Sources");
    await expect(page.getByRole("heading", { name: "Connectors" })).toBeVisible();
    await expect(page.getByRole("row").nth(1)).toBeVisible();
    const before = await page.getByRole("row").count();
    const form = page.getByRole("form", { name: "Add connector" });
    for (const url of ["http://169.254.169.254", "https://evil.example.org", "http://127.0.0.1:9"]) {
      await form.getByLabel("Name").fill("probe-connector");
      await form.getByLabel("Base URL").fill(url);
      await form.getByRole("button", { name: "Review and add…" }).click();
      await confirmDialog(page, "Add connector");
      await expect(page.getByRole("alert").filter({ hasText: /destination rejected|not an approved connector destination/i })).toBeVisible();
    }
    expect(await page.getByRole("row").count()).toBe(before);
    await context.close();
  });

  test("an approved destination can be added and shows up healthy", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "admin");
    await go(page, "#/data-sources", "Data Sources");
    const form = page.getByRole("form", { name: "Add connector" });
    await form.getByLabel("Name").fill("second-inventory");
    await form.getByLabel("Base URL").fill("http://127.0.0.1:8212");
    await form.getByRole("button", { name: "Review and add…" }).click();
    await confirmDialog(page, "Add connector");
    await expect(page.getByText('Connector "second-inventory" created.')).toBeVisible();
    await go(page, "#/integrations", "Integration Health");
    await expect(page.getByRole("heading", { name: /second-inventory/ })).toBeVisible();
    await expect(page.getByText("Nothing is sent to the external systems unless")).toBeVisible();
    await expect(page.getByText("destination authorized by the server", { exact: false }).first()).toBeVisible();
    await context.close();
  });

  test("non-admins see the limits of what they can configure", async ({ browser }) => {
    const { page, context } = await asUser(browser, MERIDIAN, "engineer");
    await go(page, "#/data-sources", "Data Sources");
    await expect(page.getByText("Connector configuration is visible to tenant administrators only.")).toBeVisible();
    await go(page, "#/integrations", "Integration Health");
    await expect(page.getByText("Per-connector status is visible to tenant administrators only.")).toBeVisible();
    await context.close();
  });

  test("onboarding checks and the domain profile come from real configuration, and the server validates edits", async ({ browser }) => {
    const { page, context } = await asUser(browser, MERIDIAN, "admin");
    await go(page, "#/onboarding", "Customer Onboarding");
    await expect(page.getByText(/\d+ of \d+ checks passing/)).toBeVisible();
    await expect(page.getByText("Authoritative asset register ingested (fleet_register)")).toBeVisible();
    await expect(page.getByText("Tenant profile, version")).toBeVisible();
    const editor = page.getByLabel("Profile (JSON)");
    const original = JSON.parse(await editor.inputValue());
    await editor.fill("{ not json");
    await page.getByRole("button", { name: "Validate and save…" }).click();
    await expect(page.getByRole("alert").first()).toBeVisible();
    await editor.fill(JSON.stringify({ ...original, asset_id_pattern: "(a+)+$" }));
    await page.getByRole("button", { name: "Validate and save…" }).click();
    await confirmDialog(page, "Save profile");
    await expect(page.getByRole("alert").filter({ hasText: /nested quantifiers|validation/i })).toBeVisible();
    await editor.fill(JSON.stringify(original));
    await page.getByRole("button", { name: "Validate and save…" }).click();
    await confirmDialog(page, "Save profile");
    await expect(page.getByText(/Profile saved as version \d+/)).toBeVisible();
    await context.close();
  });

  test("a tenant without a profile is shown as using platform defaults", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await go(page, "#/onboarding", "Customer Onboarding");
    await expect(page.getByText(/Platform defaults \(equipment maintenance\)/)).toBeVisible();
    await expect(page.getByText("Only tenant administrators can change the profile.")).toBeVisible();
    await context.close();
  });
});

test.describe("evaluation dashboard shows measured evidence honestly", () => {
  test("targets are labelled as proposals, the citation target is NOT MET, smoke and fault injection are reported", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "auditor");
    await go(page, "#/evaluation", "Evaluation Dashboard");
    await expect(page.getByText(/Targets are proposals, not results/).first()).toBeVisible();
    const citation = page.getByRole("row").filter({ hasText: "Citation correctness" }).first();
    await expect(citation).toContainText("NOT MET");
    await expect(page.getByRole("row").filter({ hasText: "Retrieval Recall@5" })).toContainText("MET");
    await expect(page.getByText("11 of 11 scenarios passed")).toBeVisible();
    await expect(page.getByText("17 of 17 checks")).toBeVisible();
    await expect(page.getByText(/not a statistically representative/i).first()).toBeVisible();
    const baselineBadge = page.locator(".badge", { hasText: "functional only" });
    await expect(baselineBadge).toHaveCount(0);
    await page.getByLabel(/Include deterministic baseline/).check();
    await expect(baselineBadge.first()).toBeVisible();
    await context.close();
  });
});

test.describe("responsive layout and keyboard use", () => {
  test("on a phone-sized screen the menu collapses and pages do not scroll sideways", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
    const page = await context.newPage();
    await page.goto("/");
    await page.getByLabel("Tenant").fill(APEX);
    await page.getByLabel("Email").fill("engineer@apex-e2e.example.test");
    await page.getByLabel("Password").fill("E2e-Test-Passw0rd!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Menu" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
    await page.getByRole("button", { name: "Menu" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await page.getByRole("link", { name: "Document Library" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Document Library" })).toBeVisible();
    for (const hash of ["#/overview", "#/documents", "#/incidents", "#/tickets", "#/approvals", "#/evaluation"]) {
      await page.evaluate((h) => { window.location.hash = h; }, hash);
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `horizontal overflow on ${hash}`).toBeLessThanOrEqual(1);
    }
    await context.close();
  });

  test("the skip link and dialogs work from the keyboard", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "supervisor");
    await page.getByRole("link", { name: "Skip to content" }).focus();
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
    await go(page, "#/incidents", "Incident Explorer");
    await page.getByLabel("Fault report").fill("Pump Z-996 shows abnormal vibration at 8.4 mm/s with grinding noise.");
    await page.getByRole("button", { name: "Analyse report" }).click();
    await expect(page.getByRole("button", { name: "Accept for ticketing…" })).toBeVisible();
    await page.getByLabel(/Justification/).fill("Keyboard test justification.");
    await page.getByRole("button", { name: "Accept for ticketing…" }).click();
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toBeHidden();
    await expect(page.getByRole("button", { name: "Accept for ticketing…" })).toBeFocused();
    await context.close();
  });
});
