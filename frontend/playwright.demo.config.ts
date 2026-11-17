import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

/**
 * Browser smoke for the one-command demonstration (scripts/demo.py smoke). Unlike playwright.config.ts it starts NOTHING: it drives the already running demo stack
 * (UI served by Vite with the /api proxy, real API, worker, disposable database, mock external systems). Run it through the launcher so the stack and credentials exist.
 */
const out = process.env.DEMO_OUT ?? path.resolve("test-results-demo");
export default defineConfig({
  testDir: "./e2e",
  testMatch: /demo-smoke\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: path.join(out, "artifacts"),
  reporter: [["list"], ["json", { outputFile: path.join(out, "playwright-results.json") }]],
  use: { baseURL: process.env.DEMO_UI_URL ?? "http://127.0.0.1:5173", trace: "retain-on-failure", screenshot: "only-on-failure", channel: "msedge" },
  projects: [{ name: "demo", use: { ...devices["Desktop Edge"], channel: "msedge" } }],
});
