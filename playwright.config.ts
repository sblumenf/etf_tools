import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command:
        ".venv/bin/uvicorn src.etf_pipeline.api.main:app --host 0.0.0.0 --port 8000",
      url: "http://localhost:8000/health",
      reuseExistingServer: true,
      timeout: 30000,
    },
    {
      command: "cd /Users/sergeblumenfeld/etf_tools/frontend && npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 30000,
    },
  ],
});
