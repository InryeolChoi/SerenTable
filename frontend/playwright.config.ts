import { defineConfig, devices } from "@playwright/test";

const origin = "http://127.0.0.1:8000";
const authEnvironment = {
  APP_ORIGIN: origin,
  APP_ENV: "development",
  AUTH_SIGNING_KEY: "playwright-only-synthetic-signing-key-20261016",
  DEMO_PARTICIPANT_PASSWORD: "synthetic-participant-password",
  DEMO_OPERATOR_PASSWORD: "synthetic-operator-password",
};
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  use: { baseURL: origin, trace: "retain-on-failure" },
  projects: [{ name: "mobile-chromium", use: { ...devices["Pixel 7"] } }],
  webServer: {
    command:
      "uv run --project .. python -m serentable.seed_demo_accounts && uv run --project .. uvicorn serentable.main:app --app-dir ../backend --host 127.0.0.1 --port 8000",
    url: `${origin}/api/health`,
    env: { ...authEnvironment, PYTHONPATH: "../backend" },
    reuseExistingServer: false,
  },
});
