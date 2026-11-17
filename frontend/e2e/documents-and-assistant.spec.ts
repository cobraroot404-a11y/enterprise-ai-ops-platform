import { expect, test } from "@playwright/test";
import { APEX, asUser, go } from "./helpers";

test.describe("document library", () => {
  test("ingests, versions, de-duplicates, filters and validates files", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await go(page, "#/documents", "Document Library");
    const name = `e2e-note-${Date.now()}.txt`;
    const body = Buffer.from(`Fictional e2e note ${Date.now()}: the cooling pump bearing was inspected.`);
    await page.getByLabel(/File \(PDF/).setInputFiles({ name, mimeType: "text/plain", buffer: body });
    await page.getByLabel("Kind").first().selectOption("other");
    await page.getByRole("button", { name: "Ingest" }).click();
    await expect(page.getByText(new RegExp(`${name} ingested`))).toBeVisible();

    await page.getByLabel("Search file name").fill("e2e-note");
    await expect(page.getByRole("button", { name })).toBeVisible();
    await page.getByRole("button", { name }).click();
    await expect(page.getByRole("heading", { name: "Document details" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "v1" }).first()).toBeVisible();

    await page.getByLabel(/File \(PDF/).setInputFiles({ name: `copy-${name}`, mimeType: "text/plain", buffer: body });
    await page.getByRole("button", { name: "Ingest" }).click();
    await expect(page.getByText(/already ingested \(identical content/)).toBeVisible();

    await page.getByLabel(/File \(PDF/).setInputFiles({ name: "malware.exe", mimeType: "application/octet-stream", buffer: Buffer.from("x") });
    await expect(page.getByText(/Unsupported file type \.exe/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Ingest" })).toBeDisabled();

    await page.getByLabel("Search file name").fill("no-such-file-anywhere");
    await expect(page.getByText("No documents match the filters.")).toBeVisible();
    await context.close();
  });

  test("read-only auditors can browse but not ingest", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "auditor");
    await go(page, "#/documents", "Document Library");
    await expect(page.getByRole("button", { name: "equipment_register.csv" })).toBeVisible();
    await expect(page.getByRole("form", { name: "Upload document" })).toHaveCount(0);
    await context.close();
  });

  test("sorts and paginates server-side", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await go(page, "#/documents", "Document Library");
    const rows = page.locator("table tbody tr td:first-child button");
    const sorted = async (order: string) => {
      const response = page.waitForResponse((r) => r.url().includes("/api/v1/documents") && r.url().includes(`order=${order}`) && r.url().includes("sort=filename"));
      await page.getByRole("button", { name: "Sort by File" }).click();
      await response;
      await expect(page.getByRole("columnheader", { name: /File/ })).toHaveAttribute("aria-sort", order === "asc" ? "ascending" : "descending");
      await page.waitForTimeout(300);
      return rows.allTextContents();
    };
    const asc = await sorted("asc");
    const desc = await sorted("desc");
    expect(desc).toEqual([...asc].reverse());
    expect(asc.length).toBeGreaterThan(3);
    await context.close();
  });
});

test.describe("AI knowledge assistant (deterministic test backends: UI behaviour, not AI quality)", () => {
  test("shows an AI-labelled answer separate from inspectable, verified evidence", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await go(page, "#/assistant", "AI Knowledge Assistant");
    await page.getByRole("textbox", { name: "Question" }).fill("What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?");
    await page.getByRole("button", { name: "Ask" }).click();
    const answer = page.getByRole("article").first();
    await expect(answer.getByText("AI-generated")).toBeVisible();
    await expect(answer.getByRole("heading", { name: "Supporting evidence" })).toBeVisible();
    await expect(answer.getByText("Retrieved evidence").first()).toBeVisible();
    await expect(answer.getByText("Verbatim quote verified").first()).toBeVisible();
    await answer.getByRole("button", { name: "Inspect" }).first().click();
    await expect(answer.getByLabel(/Citation 1 details/)).toContainText("stored passage");
    await context.close();
  });

  test("refuses to answer without evidence instead of inventing one", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await go(page, "#/assistant", "AI Knowledge Assistant");
    await page.getByRole("textbox", { name: "Question" }).fill("What is the chief executive's favourite colour?");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(page.getByText("Insufficient evidence")).toBeVisible();
    await expect(page.getByText("AI-generated")).toHaveCount(0);
    await context.close();
  });

  test("evidence-only search lists retrieved passages with similarity and no AI text", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await go(page, "#/assistant", "AI Knowledge Assistant");
    await page.getByLabel(/Search evidence only/).check();
    await page.getByRole("textbox", { name: "Question" }).fill("bearing vibration limit");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText("Nothing here was written by a model.")).toBeVisible();
    await expect(page.getByText(/similarity/).first()).toBeVisible();
    await expect(page.getByText("AI-generated")).toHaveCount(0);
    await context.close();
  });

  test("validates the question", async ({ browser }) => {
    const { page, context } = await asUser(browser, APEX, "engineer");
    await go(page, "#/assistant", "AI Knowledge Assistant");
    await page.getByRole("textbox", { name: "Question" }).fill("hi");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(page.getByText("Enter a question of at least 3 characters.")).toBeVisible();
    await context.close();
  });
});
