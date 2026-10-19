import { expect, type Page } from "@playwright/test";

// A screen can hold more than one live-region notice at the same time: a result
// notice and the loading notice of the list reloading after it are both
// role="status", and a panel below a page keeps its own error alongside the
// page's. Playwright fails fast when a locator resolves to two elements, so
// notice assertions narrow the locator by text (
// getByRole("status").filter({ hasText: "..." })) or to the one region that holds
// them, instead of asserting on the whole page.
export const origin = "http://127.0.0.1:8000";
export const participantPassword = "synthetic-participant-password";
export const operatorPassword = "synthetic-operator-password";

/** Seoul start-time label as the screens show it, used to find a slot by its start. */
export const display = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "long",
  day: "numeric",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/**
 * Mark the first-visit guide card as already seen for this page's context.
 * The card is a modal, so leaving it open blocks every later click. The card
 * itself is covered by its own test in app-ui.spec.ts, which does not call this.
 * The key mirrors STORAGE_KEY in src/guide.tsx.
 */
export async function skipGuide(page: Page) {
  await page.addInitScript(() =>
    window.sessionStorage.setItem("serentable.guide.v1", "1"),
  );
}

/** Sign in through the login screen and wait until it has been left. */
export async function login(page: Page, loginId: string, password: string) {
  await skipGuide(page);
  await page.goto("/login");
  await page.getByLabel("계정 ID", { exact: true }).fill(loginId);
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.locator("main h1")).not.toHaveText("식탁을 시작하세요");
}

// Setup goes through the same public API the screens use, with a CSRF token.
export async function call(
  page: Page,
  method: string,
  path: string,
  data: unknown,
) {
  const token = (await (await page.request.get("/api/auth/csrf")).json())
    .csrf_token;
  const response = await page.request.fetch(path, {
    method,
    data,
    headers: { Origin: origin, "X-CSRF-Token": token },
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

/** Reach a screen through the visible primary navigation or its secondary menu. */
export async function openScreen(page: Page, name: string) {
  const link = page.getByRole("link", { name, exact: true });
  if (!(await link.isVisible())) {
    await page.getByRole("button", { name: "더보기", exact: true }).click();
  }
  await link.click();
}
