import { expect, test } from "@playwright/test";
import type { APIRequestContext, Locator, Page } from "@playwright/test";
import path from "node:path";

/**
 * Browser smoke against the RUNNING demo stack (started by scripts/demo.py). Both customers are exercised through the real UI: sign in, Incident Explorer,
 * structured observation, measurement display, verification by an authorised reviewer, server-driven priority, refusal of unauthorised and same-creator
 * verification, and keyboard reachability of the new controls. The password is passed in the environment by the launcher.
 */
const PASSWORD = process.env.DEMO_PASSWORD ?? "";
const SHOTS = path.join(process.env.DEMO_OUT ?? "test-results-demo", "screenshots");

interface Flow { tenant: string; domain: string; asset: string; type: string; value: string; name: string; report: string }
const FLOWS: Flow[] = [
  { tenant: "apex-industrial", domain: "apex.example.test", asset: "P-101", type: "vibration", value: "8.4", name: "vibration_mm_s", report: "Pump P-101 shows abnormal vibration at the drive end, with a grinding noise since this morning." },
  { tenant: "meridian-fleet", domain: "meridian.example.test", asset: "VH-2101", type: "brake_pressure", value: "52", name: "brake_pressure_psi", report: "Vehicle VH-2101 shows low brake pressure with a hissing noise at the rear axle." },
];
type Role = "engineer" | "supervisor" | "auditor";

/**
 * The very first navigation of a fresh browser context is occasionally aborted before any response arrives (`net::ERR_ABORTED`, request status -1, no failure text; seen in
 * Batch 5 and Batch 6, once on the Vite UI and once on the e2e UI). Batch 7 analysis: it is transport-level (the UI server logged nothing and had a warm dependency cache),
 * not an application fault. Only THAT navigation is retried, at most twice, and every retry is recorded as a test annotation (type `navigation-retry`) together with any
 * `requestfailed` text so the launcher report can count and show them. No verification, authorization, priority or submission step is ever retried.
 */
async function open(page: Page): Promise<void> {
  const failures: string[] = [];
  page.on("requestfailed", (r) => failures.push(`${r.method()} ${r.url()} ${r.failure()?.errorText ?? ""}`));
  for (let attempt = 1; ; attempt++) {
    try {
      await page.goto("/");
      return;
    } catch (err) {
      if (attempt >= 3 || !String(err).includes("ERR_ABORTED")) throw err;
      const note = `attempt ${attempt} of 3 aborted: ${String(err).split("\n")[0]} | requestfailed: ${failures.join("; ") || "none reported"}`;
      test.info().annotations.push({ type: "navigation-retry", description: note });
      console.log(`navigation-retry ${note}`);
      await page.waitForTimeout(1500);
    }
  }
}

async function signIn(page: Page, f: Flow, role: Role): Promise<void> {
  await open(page);
  await page.getByLabel("Tenant").fill(f.tenant);
  await page.getByLabel("Email").fill(`${role}@${f.domain}`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}
async function token(request: APIRequestContext, f: Flow, role: Role): Promise<Record<string, string>> {
  const res = await request.post("/api/v1/auth/login", { data: { email: `${role}@${f.domain}`, password: PASSWORD, tenant: f.tenant } });
  expect(res.ok()).toBeTruthy();
  return { Authorization: `Bearer ${(await res.json()).access_token}` };
}
async function latest(request: APIRequestContext, f: Flow, role: Role) {
  const res = await request.get("/api/v1/incidents?limit=1&sort=created_at&order=desc", { headers: await token(request, f, role) });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).items[0] as { id: string; priority: string; measurements: { name: string; trust_status: string }[] };
}
async function tabTo(page: Page, target: Locator, max = 60): Promise<void> {
  for (let i = 0; i < max; i++) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error("could not reach the control with the Tab key");
}
async function report(page: Page, f: Flow, source?: string): Promise<void> {
  await page.evaluate(() => { window.location.hash = "#/incidents"; });
  await expect(page.getByRole("heading", { level: 2, name: "Incident Explorer" })).toBeVisible();
  await page.getByLabel("Fault report").fill(f.report);
  await page.getByRole("button", { name: "Add a structured observation" }).click();
  await page.getByLabel("Measurement type").selectOption(f.type);
  await page.getByLabel("Asset", { exact: true }).fill(f.asset);
  await page.getByLabel("Value").fill(f.value);
  if (source) await page.getByLabel(/Source reference/).fill(source);
  await page.getByRole("button", { name: "Analyse report" }).click();
}

test.describe.configure({ mode: "serial" });
for (const f of FLOWS) {
  test(`${f.tenant}: structured observation, human verification and server-driven priority through the browser`, async ({ browser, request }) => {
    expect(PASSWORD, "DEMO_PASSWORD must be provided by scripts/demo.py").not.toBe("");
    const eng = await browser.newContext();
    const page = await eng.newPage();
    await signIn(page, f, "engineer");
    await report(page, f, "demo smoke gauge");
    const card = page.locator(`[data-measurement="${f.name}"]`);
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-trust", "VALIDATED");
    await expect(card.getByText("Submitted · awaiting verification")).toBeVisible();
    await expect(card.getByText("Not used for priority")).toBeVisible();
    await expect(page.getByText("Human-verified")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Verify measurement…" })).toHaveCount(0);
    await page.screenshot({ path: path.join(SHOTS, `${f.tenant}-1-engineer-awaiting-verification.png`), fullPage: true });

    const created = await latest(request, f, "engineer");
    const before = created.priority;
    for (const role of ["engineer", "auditor"] as const) {
      const refused = await request.post(`/api/v1/incidents/${created.id}/measurements/${f.name}/verify`, { headers: await token(request, f, role), data: { decision: "approve", comment: "Demo smoke attempt.", expected_trust_status: "VALIDATED" } });
      expect(refused.status(), role).toBe(403);
    }

    const sup = await browser.newContext();
    const sp = await sup.newPage();
    await signIn(sp, f, "supervisor");
    await sp.evaluate((id) => { window.location.hash = `#/incidents?id=${id}`; }, created.id);
    await sp.reload();
    const supCard = sp.locator(`[data-measurement="${f.name}"]`);
    await expect(supCard.getByText("Submitted · awaiting verification")).toBeVisible();
    // Keyboard reachability of the review controls: Tab from the justification box to Verify, then to Reject.
    await tabTo(sp, sp.getByLabel(/Justification for/));
    await sp.keyboard.type("Demo smoke: checked against the source reading.");
    await sp.keyboard.press("Tab");
    await expect(sp.getByRole("button", { name: "Verify measurement…" })).toBeFocused();
    await sp.keyboard.press("Tab");
    await expect(sp.getByRole("button", { name: "Reject measurement…" })).toBeFocused();
    await sp.getByRole("button", { name: "Verify measurement…" }).click();
    await sp.getByRole("alertdialog").getByRole("button", { name: "Verify measurement" }).click();
    await expect(supCard.getByText("Human-verified")).toBeVisible();
    const after = await latest(request, f, "supervisor");
    expect(after.id).toBe(created.id);
    await expect(sp.getByText(new RegExp(`Priority ${before} → ${after.priority} \\(rule: [a-z_]+\\)`))).toBeVisible(); // exactly the server's decision
    await sp.screenshot({ path: path.join(SHOTS, `${f.tenant}-2-supervisor-verified.png`), fullPage: true });

    // Same-creator refusal: a supervisor who created an incident sees no controls; the API refuses as well.
    await report(sp, f);
    await expect(sp.getByText(/You created this incident, so a different reviewer must verify/)).toBeVisible();
    await expect(sp.getByRole("button", { name: "Verify measurement…" })).toHaveCount(0);
    const mine = await latest(request, f, "supervisor");
    const own = await request.post(`/api/v1/incidents/${mine.id}/measurements/${f.name}/verify`, { headers: await token(request, f, "supervisor"), data: { decision: "approve", comment: "Demo smoke same-creator attempt.", expected_trust_status: "VALIDATED" } });
    expect(own.status()).toBe(403);
    await Promise.all([eng.close(), sup.close()]);
  });
}
