// Work #10 A5-W2: browser-side authorization regressions (logout cache/back, direct admin
// URLs, and separate participant/operator sessions). The API-wide role/object sweep lives in
// tests/test_authorization_sweep.py; this spec checks what a real browser shows.
import { test, expect, devices, type Page } from "@playwright/test";
import {
  call,
  login,
  operatorPassword,
  origin,
  participantPassword,
} from "./support";

const probe = "authz.private_probe";
const adminUrls = [
  "/admin",
  "/admin/participants",
  "/admin/venues",
  "/admin/safety",
  "/admin/console",
  "/admin/events",
  "/admin/applications",
];

/** Status of a same-origin request made by the page itself, with its cookies. */
async function pageFetch(page: Page, path: string) {
  return page.evaluate(
    async (url) => (await fetch(url, { credentials: "same-origin" })).status,
    path,
  );
}

/** True when the private probe is anywhere in the visible text or in a form field. */
async function showsProbe(page: Page) {
  return page.evaluate((value) => {
    const fields = Array.from(document.querySelectorAll("input, textarea"));
    return (
      document.body.innerText.includes(value) ||
      fields.some((field) => (field as HTMLInputElement).value.includes(value))
    );
  }, probe);
}

test("로그아웃 후 뒤로 가기·새로고침에도 본인 정보가 보이지 않고 API는 401이다", async ({
  page,
}) => {
  await login(page, "participant-01", participantPassword);
  await call(page, "PUT", "/api/me/profile", {
    name: "권한 점검 이름",
    display_name: "권한 점검",
    contact: "010-0000-0099",
    instagram_id: probe,
    birth_year: 1995,
    gender: "기록한 성별",
    occupation: "합성 직업",
    interests: ["reading"],
    self_traits: ["listener"],
    desired_traits: ["different"],
    meal_budget_bands: ["10000_20000"],
  });
  // Full document loads, so Back has real history entries to return to.
  await page.goto("/participant/history");
  await page.goto("/participant/profile");
  const form = page.getByRole("form", { name: "본인 프로필" });
  await expect(form.getByLabel("Instagram ID")).toHaveValue(probe);

  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  const loginForm = page.getByRole("form", { name: "합성 계정 로그인" });
  await expect(loginForm).toBeVisible();
  expect(await showsProbe(page)).toBe(false);

  await page.goBack();
  await expect(loginForm).toBeVisible();
  await expect(form).toHaveCount(0);
  expect(await showsProbe(page)).toBe(false);
  expect(await pageFetch(page, "/api/me/profile")).toBe(401);

  await page.goForward();
  await page.reload();
  await expect(loginForm).toBeVisible();
  expect(await showsProbe(page)).toBe(false);
  for (const path of [
    "/api/auth/me",
    "/api/me/profile",
    "/api/me/applications",
    "/api/me/notifications",
  ])
    expect(await pageFetch(page, path)).toBe(401);
  const profile = await page.request.get("/api/me/profile");
  expect(profile.status()).toBe(401);
  expect(profile.headers()["cache-control"]).toBe("no-store");
});

test("참가자가 운영자 주소를 직접 열면 거절 화면만 보고 운영 API는 성공하지 않는다", async ({
  page,
}) => {
  const adminResponses: string[] = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api/admin/") && response.ok())
      adminResponses.push(url.pathname);
  });
  await login(page, "participant-01", participantPassword);
  for (const url of adminUrls) {
    await page.goto(url);
    await expect(
      page.getByRole("heading", { name: "접근 권한이 없습니다" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "운영 현황" })).toHaveCount(0);
  }
  for (const path of [
    "/api/admin/session",
    "/api/admin/participants",
    "/api/admin/applications",
    "/api/admin/reports",
    "/api/admin/exports/applications.csv",
  ])
    expect(await pageFetch(page, path)).toBe(403);
  expect(adminResponses).toEqual([]);
});

test("운영자와 참가자 세션을 다른 브라우저 문맥에서 동시에 써도 서로 섞이지 않는다", async ({
  browser,
}) => {
  const contextOptions = { ...devices["Pixel 7"], baseURL: origin };
  const operatorContext = await browser.newContext(contextOptions);
  const participantContext = await browser.newContext(contextOptions);
  try {
    const operator = await operatorContext.newPage();
    const participant = await participantContext.newPage();
    await login(operator, "operator", operatorPassword);
    await login(participant, "participant-02", participantPassword);

    const operatorMe = await (await operator.request.get("/api/auth/me")).json();
    const participantMe = await (
      await participant.request.get("/api/auth/me")
    ).json();
    expect(operatorMe.user.role).toBe("operator");
    expect(participantMe.user).toMatchObject({
      role: "participant",
      login_id: "participant-02",
    });
    const sessionCookie = async (context: typeof operatorContext) =>
      (await context.cookies()).find((c) => c.name.endsWith("serentable_session"))
        ?.value;
    expect(await sessionCookie(operatorContext)).toBeTruthy();
    expect(await sessionCookie(operatorContext)).not.toBe(
      await sessionCookie(participantContext),
    );

    expect(await pageFetch(operator, "/api/admin/participants")).toBe(200);
    expect(await pageFetch(participant, "/api/admin/participants")).toBe(403);
    expect(await pageFetch(operator, "/api/me/profile")).toBe(403);
    expect(await pageFetch(participant, "/api/me/profile")).toBe(200);

    // Each screen follows its own session even when both open the other's URL.
    await participant.goto("/admin/participants");
    await expect(
      participant.getByRole("heading", { name: "접근 권한이 없습니다" }),
    ).toBeVisible();
    await operator.goto("/admin/participants");
    await expect(
      operator.getByRole("heading", { name: "합성 참가자 관리" }),
    ).toBeVisible();

    // Logging one out revokes only that session.
    await participant
      .getByRole("button", { name: "로그아웃", exact: true })
      .click();
    await expect(
      participant.getByRole("form", { name: "합성 계정 로그인" }),
    ).toBeVisible();
    expect(await pageFetch(participant, "/api/auth/me")).toBe(401);
    expect(await pageFetch(operator, "/api/admin/session")).toBe(200);
    await operator.reload();
    await expect(
      operator.getByRole("heading", { name: "합성 참가자 관리" }),
    ).toBeVisible();
  } finally {
    await operatorContext.close();
    await participantContext.close();
  }
});
