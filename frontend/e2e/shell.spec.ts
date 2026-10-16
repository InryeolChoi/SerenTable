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

test("미완성 프로필과 목적별 동의가 실제 DB에 저장되고 새로고침 후 유지된다", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("link", { name: "프로필", exact: true }).click();
  await expect(page.getByRole("form", { name: "본인 프로필" })).toBeVisible();
  const form = page.getByRole("form", { name: "본인 프로필" });
  await form.getByLabel("이름 원문").fill("합성 참가자 하나");
  for (const label of [
    "표시명",
    "연락처",
    "Instagram ID",
    "직업",
    "출생연도",
    "성별",
  ])
    await form.getByLabel(label).fill("");
  for (const checkbox of await form.getByRole("checkbox").all())
    await checkbox.uncheck();
  for (const group of ["못 먹는 음식", "알레르기"])
    await form
      .getByRole("group", { name: group, exact: true })
      .getByLabel("확인 상태")
      .selectOption("unknown");
  await page.getByRole("button", { name: "프로필 저장", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "미완성 프로필을 저장했습니다",
  );
  await page.reload();
  await expect(form.getByLabel("이름 원문")).toHaveValue("합성 참가자 하나");
  await expect(
    form
      .getByRole("group", { name: "알레르기", exact: true })
      .getByLabel("확인 상태"),
  ).toHaveValue("unknown");
  await form.getByLabel("표시명").fill("테스트 식탁 하나");
  await form.getByLabel("연락처").fill("010-0000-0001");
  await form.getByLabel("Instagram ID").fill("synthetic.table_01");
  await form.getByLabel("직업").fill("합성 직업");
  await form.getByLabel("출생연도").fill("1995");
  await form.getByLabel("성별").fill("여성");
  await form.getByRole("checkbox", { name: "INTJ", exact: true }).check();
  await form.getByRole("checkbox", { name: "ENFP", exact: true }).check();
  for (const group of [
    "요즘 관심사",
    "나는 어떤 사람인가요",
    "만나고 싶은 사람",
    "식사에 쓸 수 있는 예산",
  ])
    await form
      .getByRole("group", { name: group, exact: true })
      .getByRole("checkbox")
      .first()
      .check();
  await page.getByRole("button", { name: "프로필 저장", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "필요한 항목이 모두 입력되었습니다",
  );
  await page.reload();
  await expect(form.getByLabel("Instagram ID")).toHaveValue(
    "synthetic.table_01",
  );
  await expect(
    form.getByRole("checkbox", { name: "INTJ", exact: true }),
  ).toBeChecked();
  await expect(
    form.getByRole("checkbox", { name: "ENFP", exact: true }),
  ).toBeChecked();
  await page.getByRole("link", { name: "동의", exact: true }).click();
  await expect(page.getByText("버전: demo-2026-10-16").first()).toBeVisible();
  await expect(page.locator(".policy-body")).toHaveCount(2);
  for (const checkbox of await page.getByRole("checkbox").all())
    await checkbox.uncheck();
  await page.getByRole("button", { name: "동의 선택 저장" }).click();
  await expect(
    page.getByText("필수 동의가 완료되지 않았습니다.", { exact: true }),
  ).toBeVisible();
  for (const checkbox of await page.getByRole("checkbox").all())
    await checkbox.check();
  await page.getByRole("button", { name: "동의 선택 저장" }).click();
  await expect(
    page.getByText("필수 동의가 완료되었습니다.", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  for (const checkbox of await page.getByRole("checkbox").all())
    await expect(checkbox).toBeChecked();
  await page.getByRole("link", { name: "입력 상태", exact: true }).click();
  await expect(page.getByText("입력 완료", { exact: true })).toBeVisible();
  await expect(page.getByText("동의 완료", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("연결 실패·입력 오류·서버 세션 철회 후에도 같은 계정의 미저장 입력이 유지된다", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("link", { name: "프로필", exact: true }).click();
  const form = page.getByRole("form", { name: "본인 프로필" });
  await expect(form).toBeVisible();
  await form.getByLabel("표시명").fill("만료 전 미저장 표시명");
  await page.route("**/api/me/profile", async (route) => {
    if (route.request().method() === "PUT") await route.abort("failed");
    else await route.continue();
  });
  await page.getByRole("button", { name: "프로필 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "서버에 연결하지 못했습니다",
  );
  await expect(form.getByLabel("표시명")).toHaveValue("만료 전 미저장 표시명");
  await page.unroute("**/api/me/profile");
  await form.getByLabel("Instagram ID").fill("invalid@synthetic");
  await page.getByRole("button", { name: "프로필 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Instagram ID의 입력 형식",
  );
  await expect(form.getByLabel("Instagram ID")).toHaveValue(
    "invalid@synthetic",
  );
  await form.getByLabel("Instagram ID").fill("synthetic.table_01");
  const csrf = await (await page.request.get("/api/auth/csrf")).json();
  const revoked = await page.request.post("/api/auth/logout", {
    headers: {
      Origin: "http://127.0.0.1:8000",
      "X-CSRF-Token": csrf.csrf_token,
    },
  });
  expect(revoked.status()).toBe(200);
  await page.getByRole("button", { name: "프로필 저장", exact: true }).click();
  await expect(
    page.getByRole("form", { name: "합성 계정 로그인" }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("세션이 만료되었습니다");
  await page.getByLabel("계정 ID", { exact: true }).fill("participant-01");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("synthetic-participant-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await page.getByRole("link", { name: "프로필", exact: true }).click();
  await expect(form.getByLabel("표시명")).toHaveValue("만료 전 미저장 표시명");
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await page.getByLabel("계정 ID", { exact: true }).fill("participant-02");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("synthetic-participant-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await page.getByRole("link", { name: "프로필", exact: true }).click();
  await expect(form.getByLabel("표시명")).not.toHaveValue(
    "만료 전 미저장 표시명",
  );
});

test("운영자는 합성 참가자 상세를 확인하고 모바일·데스크톱에서 잘림 없이 읽는다", async ({
  page,
}, testInfo) => {
  await login(page, "operator");
  await page
    .getByRole("button", { name: "상세 보기: participant-01", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "테스트 식탁 하나", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".detail-list")).toContainText(
    "synthetic.table_01",
  );
  await expect(page.locator(".detail-list")).toContainText("알레르기");
  for (const width of [360, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: testInfo.outputPath(`admin-${width}.png`),
      fullPage: true,
    });
  }
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  const session = await (await page.request.get("/api/auth/me")).json();
  expect(Object.keys(session)).toEqual(["user"]);
  expect(Object.keys(session.user).sort()).toEqual(["id", "login_id", "role"]);
});
