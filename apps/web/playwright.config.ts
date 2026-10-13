import { defineConfig, devices } from "@playwright/test";

import { ADMIN } from "./e2e/helpers";

// End-to-end: a fresh seeded API (SQLite, offline AI) plus a production build of the web app.
// Next.js bakes rewrites in at build time, so the build gets API_URL too.
const API_PORT = 8765;
const WEB_PORT = 3100;
const python = process.env.PYTHON ?? "python";
const db = process.env.E2E_DB ?? "/tmp/eduverse-e2e.db";


export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `rm -f ${db} && ${python} -m app.seed && ${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../api",
      env: {
        EDU_ENV: "development",
        EDU_DATABASE_URL: `sqlite:///${db}`,
        EDU_ADMIN_EMAIL: ADMIN.email,
        EDU_ADMIN_PASSWORD: ADMIN.password,
        EDU_ANTHROPIC_API_KEY: "",
        EDU_OPENAI_API_KEY: "",
        EDU_RATE_LIMIT_AUTH: "1000",
        EDU_UPLOAD_DIR: "/tmp/eduverse-e2e-uploads",
      },
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npx next build && npx next start -H 127.0.0.1 -p ${WEB_PORT}`,
      env: { API_URL: `http://127.0.0.1:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
