import { defineConfig, devices } from "@playwright/test";

const realAi = process.env.E2E_REAL_AI === "1";
// Browser channel: default Microsoft Edge; E2E_BROWSER_CHANNEL=chrome runs the same suite in the installed Google Chrome (no download).
const channel = process.env.E2E_BROWSER_CHANNEL ?? "msedge";
// Run-only HMAC signing secret for the webhook e2e: set before the stack starts (the web server inherits this environment) and read by the test. Never written anywhere.
process.env.WEBHOOK_E2E_SECRET ??= `e2e-${Math.random().toString(16).slice(2)}${Date.now().toString(16)}-signing`;

/**
 * End-to-end tests against an isolated, seeded stack (scripts/e2e_stack.py): real API, worker, PostgreSQL and mock
 * external systems. Default run uses the deterministic test-only AI backends (functional UI behaviour). The real-AI
 * project (E2E_REAL_AI=1 npx playwright test -c playwright.config.ts --project=real-ai) uses Ollama + MiniLM and is a
 * separate, clearly-labelled smoke run. Browser: the Microsoft Edge already installed on the machine (no download).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: realAi ? 240_000 : 60_000,
  expect: { timeout: realAi ? 60_000 : 10_000 },
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  use: { baseURL: "http://127.0.0.1:8220", trace: "retain-on-failure", screenshot: "only-on-failure", channel },
  projects: realAi
    ? [{ name: "real-ai", testMatch: /real-ai\.spec\.ts/, use: { ...devices["Desktop Edge"], channel } }]
    : [{ name: "deterministic", testIgnore: /(real-ai|demo-smoke)\.spec\.ts/, use: { ...devices["Desktop Edge"], channel } }],
  webServer: { command: "node e2e/start-stack.mjs", url: "http://127.0.0.1:8220", timeout: 300_000, reuseExistingServer: false, stdout: "ignore", stderr: "ignore" },
});
