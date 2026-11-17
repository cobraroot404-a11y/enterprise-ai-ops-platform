import { createHmac } from "node:crypto";
import { expect, test } from "@playwright/test";
import { APEX, asUser, confirmDialog, go } from "./helpers";

// The signing secret is a run-only value set by playwright.config.ts in the environment of the stack and of this test: it is never stored in the repository or in the database.
const SECRET = process.env.WEBHOOK_E2E_SECRET ?? "";
const sign = (ts: string, id: string, body: string) => "sha256=" + createHmac("sha256", SECRET).update(`${ts}.${id}.`).update(body).digest("hex");

test.describe("signed webhook endpoint (administrator workflow and a real delivery)", () => {
  test("provision an endpoint in the UI, deliver a signed record, see it processed, then disable the endpoint", async ({ browser }) => {
    expect(SECRET.length).toBeGreaterThan(20);
    const { page, context } = await asUser(browser, APEX, "admin");
    await go(page, "#/data-sources", "Data Sources");
    const name = `e2e-feed-${Date.now()}`;
    const form = page.getByRole("form", { name: "Add webhook endpoint" });
    await form.getByLabel("Endpoint name").fill(name);
    await form.getByLabel(/Signing secret variable name/).fill("lower-case-is-not-a-variable-name");
    await form.getByRole("button", { name: "Review and add…" }).click();
    await expect(form.getByText(/^Enter the NAME of a server environment variable/)).toBeVisible();  // validated locally; the server was not called
    await form.getByLabel(/Signing secret variable name/).fill("WEBHOOK_E2E_SECRET");
    await form.getByRole("button", { name: "Review and add…" }).click();
    await confirmDialog(page, "Add endpoint");
    await expect(page.getByText(/Senders post signed deliveries to \/api\/v1\/webhooks\//)).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: name });
    await expect(row.getByText("configured on the server")).toBeVisible();  // the server has the variable; its value is never shown
    const path = (await row.locator("code").innerText()).trim();

    const record = JSON.stringify({ id: `E2E-${Date.now()}`, title: "E2E webhook bulletin", body: "Seal on pump P-101 weeps under load; replace the seal.", updated_at: "v1" });
    const send = (ts: string, id: string, signature: string) => page.request.post(path, { data: record, headers: { "Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Delivery-Id": id, "X-Webhook-Signature": signature } });
    const ts = String(Math.floor(Date.now() / 1000));
    expect((await send(ts, "e2e-wrong-0001", "sha256=" + "0".repeat(64))).status()).toBe(401);
    const good = await send(ts, "e2e-good-0001", sign(ts, "e2e-good-0001", record));
    expect(good.status()).toBe(202);
    expect((await good.json()).status).toBe("QUEUED");  // queued, not processed
    expect((await send(ts, "e2e-good-0001", sign(ts, "e2e-good-0001", record))).status()).toBe(409);  // replay of the same delivery id

    const activity = page.getByRole("heading", { name: "Recent synchronisations and webhook deliveries" }).locator("xpath=ancestor::section[1]");
    await expect(async () => {
      await activity.getByRole("button", { name: "Refresh" }).click();
      await expect(activity.getByRole("row").filter({ hasText: name })).toContainText("synced: 1 created", { timeout: 2000 });
    }).toPass({ timeout: 40_000 });

    await row.getByRole("button", { name: "Disable" }).click();
    await expect(row.getByText("disabled")).toBeVisible();
    expect((await send(ts, "e2e-good-0002", sign(ts, "e2e-good-0002", record))).status()).toBe(401);  // a disabled endpoint rejects even a correctly signed delivery
    await context.close();
  });
});
