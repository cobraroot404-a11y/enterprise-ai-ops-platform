import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { APEX, MERIDIAN, analyse, approvedApexTicket, asUser, go } from "./helpers";

/** Captures the review screenshots in docs/phase6/screenshots. Opt-in: E2E_SCREENSHOTS=1 npx playwright test screenshots */
test.skip(process.env.E2E_SCREENSHOTS !== "1", "screenshots are captured on demand");
const here = path.dirname(fileURLToPath(import.meta.url));
const out = (name: string) => path.resolve(here, "..", "..", "docs", "phase6", "screenshots", `${name}.png`);

test("capture review screenshots", async ({ browser, request }) => {
  const admin = await asUser(browser, MERIDIAN, "admin");
  await go(admin.page, "#/overview", "Overview");
  await expect(admin.page.getByRole("listitem").filter({ hasText: "Documents" })).toBeVisible();
  await admin.page.screenshot({ path: out("01-overview-meridian"), fullPage: true });
  await go(admin.page, "#/onboarding", "Customer Onboarding");
  await expect(admin.page.getByText(/checks passing/)).toBeVisible();
  await admin.page.screenshot({ path: out("02-onboarding-meridian"), fullPage: true });
  await go(admin.page, "#/evaluation", "Evaluation Dashboard");
  await expect(admin.page.getByText("NOT MET").first()).toBeVisible();
  await admin.page.screenshot({ path: out("07-evaluation"), fullPage: true });

  const sup = await asUser(browser, APEX, "supervisor");
  await analyse(sup.page, "Pump Z-995 shows abnormal vibration at 8.4 mm/s with a grinding noise.");
  await expect(sup.page.getByText("This incident is blocked.")).toBeVisible();
  await sup.page.screenshot({ path: out("03-incident-blocked-review"), fullPage: true });

  const eng = await asUser(browser, APEX, "engineer");
  await go(eng.page, "#/assistant", "AI Knowledge Assistant");
  await eng.page.getByRole("textbox", { name: "Question" }).fill("What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?");
  await eng.page.getByRole("button", { name: "Ask" }).click();
  await expect(eng.page.getByText("Supporting evidence")).toBeVisible();
  await eng.page.getByRole("button", { name: "Inspect" }).first().click();
  await eng.page.screenshot({ path: out("04-assistant-evidence"), fullPage: true });

  const { ticketId } = await approvedApexTicket(request);
  await sup.page.evaluate((i) => { window.location.hash = `#/tickets?id=${i}`; }, ticketId);
  await sup.page.reload();
  await expect(sup.page.getByText(/Confirmed by the external system/)).toBeVisible({ timeout: 30_000 });
  await sup.page.screenshot({ path: out("05-tickets"), fullPage: true });

  const phone = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const p = await phone.newPage();
  await p.goto("/");
  await p.getByLabel("Tenant").fill(APEX);
  await p.getByLabel("Email").fill("engineer@apex-e2e.example.test");
  await p.getByLabel("Password").fill("E2e-Test-Passw0rd!");
  await p.getByRole("button", { name: "Sign in" }).click();
  await expect(p.getByRole("button", { name: "Menu" })).toBeVisible();
  await p.screenshot({ path: out("06-mobile-overview"), fullPage: true });
  await Promise.all([admin.context.close(), sup.context.close(), eng.context.close(), phone.close()]);
});
