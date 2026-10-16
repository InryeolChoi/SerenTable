import { test, expect, type Page } from "@playwright/test";

async function login(
  page: Page,
  role: "participant" | "operator" = "participant",
) {
  await page.goto("/login");
  await page
    .getByLabel("계정 ID", { exact: true })
    .fill(role === "operator" ? "operator" : "participant-01");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill(
      role === "operator"
        ? "synthetic-operator-password"
        : "synthetic-participant-password",
    );
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: role === "operator" ? "합성 참가자 관리" : "내 식탁 준비",
    }),
  ).toBeVisible();
}

test("합성 참가자가 실제 로그인하고 권한 거절과 로그아웃을 확인한다", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("계정 ID", { exact: true }).fill("participant-01");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("incorrect-synthetic-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("계정 ID 또는 비밀번호");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("synthetic-participant-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "내 식탁 준비" }),
  ).toBeVisible();
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "접근 권한이 없습니다" }),
  ).toBeVisible();
  const denied = await page.request.get("/api/admin/participants");
  expect(denied.status()).toBe(403);
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(
    page.getByRole("form", { name: "합성 계정 로그인" }),
  ).toBeVisible();
  expect((await page.request.get("/api/me/profile")).status()).toBe(401);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
});
