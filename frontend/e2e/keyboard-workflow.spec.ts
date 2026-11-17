import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { APEX, PASSWORD } from "./helpers";

/**
 * Keyboard-only walk through the critical workflow (sign in, navigate, report a fault, review it, confirm): no mouse clicks and
 * no programmatic .focus() on the way. This complements the axe audit; it is not a screen-reader audit.
 */
async function tabTo(page: Page, target: Locator, max = 80): Promise<void> {
  for (let i = 0; i < max; i++) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`could not reach ${target} with the Tab key within ${max} presses`);
}

test("critical workflow is operable with the keyboard alone", async ({ page }) => {
  await page.goto("/");
  await tabTo(page, page.getByLabel("Tenant"));
  await page.keyboard.type(APEX);
  await page.keyboard.press("Tab");
  await page.keyboard.type("supervisor@apex-e2e.example.test");
  await page.keyboard.press("Tab");
  await page.keyboard.type(PASSWORD);
  await page.keyboard.press("Enter"); // submits the form
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Overview" })).toBeFocused(); // focus moved to the new page

  await tabTo(page, page.getByRole("link", { name: "Incident Explorer" }));
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 2, name: "Incident Explorer" })).toBeFocused();

  await tabTo(page, page.getByLabel("Fault report"));
  await page.keyboard.type("Pump Z-902 shows abnormal vibration at 8.4 mm/s with a grinding noise.");
  // Batch 5 added the optional number-format select and the structured-observation controls between the report and the button: reach the button by keyboard.
  await tabTo(page, page.getByRole("button", { name: "Analyse report" }));
  await expect(page.getByRole("button", { name: "Analyse report" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("This incident is blocked.")).toBeVisible();

  await tabTo(page, page.getByLabel(/Justification/));
  await page.keyboard.type("Keyboard-only review: asset checked on site.");
  await page.keyboard.press("Tab");
  const accept = page.getByRole("button", { name: "Accept for ticketing…" });
  await expect(accept).toBeFocused();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused(); // focus moves into the dialog
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Accept incident" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused(); // focus is trapped inside the dialog
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(accept).toBeFocused(); // focus returns to the control that opened it

  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter"); // confirm with the keyboard
  await expect(page.getByText("Human-reviewed · accepted").first()).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /Incident accepted by human review/ })).toBeVisible(); // announced politely
});
