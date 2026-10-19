import { defineConfig, devices } from "@playwright/test";

const origin = "http://127.0.0.1:8000";
const engine = process.env.E2E_BROWSER ?? "chromium";
if (engine !== "chromium" && engine !== "webkit") {
  throw new Error("E2E_BROWSER must be chromium or webkit");
}
const authEnvironment = {
  APP_ORIGIN: origin,
  APP_ENV: "development",
  AUTH_SIGNING_KEY: "playwright-only-synthetic-signing-key-20261016",
  DEMO_PARTICIPANT_PASSWORD: "synthetic-participant-password",
  DEMO_OPERATOR_PASSWORD: "synthetic-operator-password",
};
export default defineConfig({
  testDir: "./e2e",
  outputDir: `./test-results/${engine}`,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: origin, trace: "retain-on-failure" },
  projects:
    engine === "webkit"
      ? [
          {
            name: "mobile-webkit",
            use: { ...devices["iPhone 13"], browserName: "webkit" },
          },
        ]
      : [{ name: "mobile-chromium", use: { ...devices["Pixel 7"] } }],
  webServer: {
    // Each run starts from an empty local schema (the reset refuses non-local databases).
    command:
      "node e2e/reset-database.mjs && uv run --project .. python -m serentable.seed_demo_accounts && uv run --project .. uvicorn serentable.main:app --app-dir ../backend --host 127.0.0.1 --port 8000",
    url: `${origin}/api/health`,
    env: { ...authEnvironment, PYTHONPATH: "../backend" },
    reuseExistingServer: false,
  },
});
