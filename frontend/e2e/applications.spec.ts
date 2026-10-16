import { test, expect, type Page } from "@playwright/test";

const origin = "http://127.0.0.1:8000";
const display = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "long",
  day: "numeric",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

async function login(page: Page, loginId: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("계정 ID", { exact: true }).fill(loginId);
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.locator("main h1")).not.toHaveText("식탁을 시작하세요");
}

// Setup goes through the same public API the screens use, with a CSRF token.
async function call(page: Page, method: string, path: string, data: unknown) {
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

// The E2E database persists between runs, so each run uses distinct start times.
async function createSlot(page: Page, daysAhead: number, region: string) {
  const start = new Date(Date.now() + daysAhead * 86400_000);
  start.setUTCSeconds(0, 0);
  const iso = (offsetHours: number) =>
    new Date(start.getTime() + offsetHours * 3600_000).toISOString();
  const body = await call(page, "POST", "/api/admin/event-slots", {
    region_code: region,
    starts_at: iso(0),
    ends_at: iso(2),
    closes_at: iso(-48),
    matches_at: iso(-24),
    capacity: 12,
  });
  return body.event_slot as { id: string; starts_at: string };
}

test("참가자가 복수 후보 회차를 골라 검토 후 신청하고 상태를 확인한다", async ({
  browser,
}) => {
  const days = 30 + Math.floor(Math.random() * 300);
  const operatorContext = await browser.newContext();
  const operator = await operatorContext.newPage();
  await login(operator, "operator", "synthetic-operator-password");
  const first = await createSlot(operator, days, "jamsil");
  const second = await createSlot(operator, days + 1, "gangnam");
  const firstName = `${display.format(new Date(first.starts_at))}`;
  const secondName = `${display.format(new Date(second.starts_at))}`;
  // Another slot's matching time can equal a start time, so anchor on the start.
  const startsWith = (text: string) =>
    new RegExp(`^${text.replace(/[()]/g, "\\$&")} ~`);

  const participantContext = await browser.newContext();
  const participant = await participantContext.newPage();
  await login(participant, "participant-04", "synthetic-participant-password");
  await call(participant, "PUT", "/api/me/profile", {
    name: "합성 이름",
    display_name: "신청 식탁",
    contact: "010-0000-0000",
    instagram_id: "synthetic_apply",
    birth_year: 1994,
    gender: "기록한 성별",
    occupation: "합성 직업",
    interests: ["music"],
    self_traits: ["listener"],
    desired_traits: ["similar"],
    meal_budget_bands: ["20000_30000"],
  });
  await call(participant, "PUT", "/api/me/consents", {
    consents: [
      { purpose: "privacy", version: "demo-2026-10-16", accepted: true },
      { purpose: "operation", version: "demo-2026-10-16", accepted: false },
    ],
  });

  await participant
    .getByRole("link", { name: "일정 신청", exact: true })
    .click();
  const picker = participant.getByRole("group", { name: "후보 회차" });
  await picker.getByRole("checkbox", { name: startsWith(firstName) }).check();
  await picker.getByRole("checkbox", { name: startsWith(secondName) }).check();
  await participant.getByRole("button", { name: "선택 확인" }).click();
  await expect(participant).toHaveURL(/\/participant\/apply\/review$/);
  const review = participant.getByRole("list", { name: "선택한 후보 회차" });
  await expect(review.getByRole("listitem")).toHaveCount(2);
  await expect(review).toContainText("잠실");
  await expect(review).toContainText("강남");
  await expect(participant.getByText("결제가 아닙니다")).toBeVisible();

  // The missing consent is reported, and the selection survives the detour.
  await participant.getByRole("button", { name: "신청 제출" }).click();
  await expect(participant.getByRole("alert")).toContainText("필수 동의");
  await call(participant, "PUT", "/api/me/consents", {
    consents: [
      { purpose: "operation", version: "demo-2026-10-16", accepted: true },
    ],
  });
  await participant.getByRole("button", { name: "선택 수정" }).click();
  await expect(participant).toHaveURL(/\/participant\/apply$/);
  await expect(
    picker.getByRole("checkbox", { name: startsWith(secondName) }),
  ).toBeChecked();
  await participant.getByRole("button", { name: "선택 확인" }).click();
  await participant.getByRole("button", { name: "신청 제출" }).click();
  await expect(participant.getByRole("status")).toContainText(
    "신청을 제출했습니다",
  );

  await participant
    .getByRole("link", { name: "입력 상태", exact: true })
    .click();
  const mine = participant
    .getByRole("list", { name: "내 신청" })
    // Each application is a direct item; its candidates form a nested list.
    .locator(":scope > li")
    .filter({ hasText: firstName });
  await expect(mine).toHaveCount(1);
  await expect(mine).toContainText("신청 완료");
  await expect(mine).toContainText("결제: 결제 필요");
  await expect(mine).toContainText(secondName);
  for (const width of [360, 1440]) {
    await participant.setViewportSize({ width, height: 900 });
    expect(
      await participant.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }

  await operator.goto("/admin/applications");
  const row = operator
    .getByRole("list", { name: "신청 목록" })
    // Each application is a direct item; its candidates form a nested list.
    .locator(":scope > li")
    .filter({ hasText: firstName });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("participant-04");
  await expect(row).toContainText("신청 완료");
  await expect(row).toContainText("결제: 결제 필요");

  await mine.getByRole("button", { name: "신청 취소" }).click();
  await expect(mine).toContainText("신청 취소됨");
  await expect(mine.getByRole("button", { name: "신청 취소" })).toHaveCount(0);
  await participant.goto("/admin/applications");
  await expect(
    participant.getByRole("heading", { name: "접근 권한이 없습니다" }),
  ).toBeVisible();
  await operatorContext.close();
  await participantContext.close();
});
