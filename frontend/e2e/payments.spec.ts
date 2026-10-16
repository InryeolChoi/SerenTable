import { execFileSync } from "node:child_process";
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
const account = "participant-03";

// The E2E database persists between runs and an earlier run's membership would cover
// this run's applications, so this synthetic account's passes are cleared first.
test.beforeAll(() => {
  execFileSync(
    "uv",
    [
      "run",
      "--project",
      "..",
      "python",
      "-c",
      `from sqlalchemy import text
from serentable.database import database_engine
with database_engine().begin() as c:
    user = {"login": "${account}"}
    c.execute(text("DELETE FROM entitlement WHERE user_id = (SELECT id FROM app_user WHERE login_id = :login)"), user)
    c.execute(text("DELETE FROM payment WHERE user_id = (SELECT id FROM app_user WHERE login_id = :login)"), user)`,
    ],
    { env: { ...process.env, PYTHONPATH: "../backend" }, stdio: "inherit" },
  );
});

async function login(page: Page, loginId: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("계정 ID", { exact: true }).fill(loginId);
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.locator("main h1")).not.toHaveText("식탁을 시작하세요");
}

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

async function createSlot(page: Page, daysAhead: number) {
  const start = new Date(Date.now() + daysAhead * 86400_000);
  start.setUTCSeconds(0, 0);
  const iso = (offsetHours: number) =>
    new Date(start.getTime() + offsetHours * 3600_000).toISOString();
  const body = await call(page, "POST", "/api/admin/event-slots", {
    region_code: "euljiro",
    starts_at: iso(0),
    ends_at: iso(2),
    closes_at: iso(-48),
    matches_at: iso(-24),
    capacity: 12,
  });
  return display.format(new Date(body.event_slot.starts_at));
}

async function applyFor(participant: Page, slotName: string) {
  await participant
    .getByRole("link", { name: "일정 신청", exact: true })
    .click();
  await participant
    .getByRole("group", { name: "후보 회차" })
    .getByRole("checkbox", {
      name: new RegExp(`^${slotName.replace(/[()]/g, "\\$&")} ~`),
    })
    .check();
  await participant.getByRole("button", { name: "선택 확인" }).click();
}

test("참가자가 이용권을 골라 모의 결제하고 실패 후 재시도하며 멤버십이 다음 신청을 포함한다", async ({
  browser,
}) => {
  // Random offsets keep slots distinct across runs; the first two fall within one month.
  const days = 5 + Math.floor(Math.random() * 10) + Math.random();
  const operatorContext = await browser.newContext();
  const operator = await operatorContext.newPage();
  await login(operator, "operator", "synthetic-operator-password");
  const first = await createSlot(operator, days);
  const second = await createSlot(operator, days + 3);

  const participantContext = await browser.newContext();
  const participant = await participantContext.newPage();
  await login(participant, account, "synthetic-participant-password");
  await call(participant, "PUT", "/api/me/profile", {
    name: "합성 이름",
    display_name: "결제 식탁",
    contact: "010-0000-0000",
    instagram_id: "synthetic_pay",
    birth_year: 1993,
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
      { purpose: "operation", version: "demo-2026-10-16", accepted: true },
    ],
  });

  await applyFor(participant, first);
  const products = participant.getByRole("radiogroup", { name: "이용권" });
  await expect(products).toContainText("1회권 · 9,900원");
  await expect(products).toContainText("멤버십 6개월 · 120,000원");
  await products.getByRole("radio", { name: /^1회권/ }).check();
  await participant.getByRole("button", { name: "신청 제출" }).click();

  // The mock payment step: clearly not a real charge, refund policy shown before paying.
  const mock = participant.getByRole("region", { name: "모의 결제" });
  await expect(mock).toContainText("모의 결제 · 실제 결제가 발생하지 않습니다");
  await expect(mock).toContainText("화요일 24:00 이후 환불 불가");
  await expect(mock).toContainText("세부 환불 정책 미정");
  await expect(mock).toContainText("결제 금액 9,900원");
  await mock.getByRole("checkbox", { name: /실패 시뮬레이션/ }).check();
  await mock.getByRole("button", { name: "모의 결제하기" }).click();
  await expect(mock.getByRole("alert")).toContainText("결제 실패");
  await mock.getByRole("checkbox", { name: /실패 시뮬레이션/ }).uncheck();
  await mock.getByRole("radio", { name: /^멤버십 1개월/ }).check();
  await expect(mock).toContainText("결제 금액 35,000원");
  await mock.getByRole("button", { name: "모의 결제하기" }).click();
  await expect(mock.getByRole("status")).toContainText("결제 완료");

  // A second application inside the membership period needs no payment.
  await participant.getByRole("button", { name: "내 신청 보기" }).click();
  await applyFor(participant, second);
  await participant.getByRole("button", { name: "신청 제출" }).click();
  await expect(participant.getByRole("status").first()).toContainText(
    "보유한 멤버십으로 결제 없이",
  );

  await participant
    .getByRole("link", { name: "입력 상태", exact: true })
    .click();
  const mine = participant
    .getByRole("list", { name: "내 신청" })
    .locator(":scope > li");
  await expect(mine.filter({ hasText: first })).toContainText("결제 완료");
  await expect(mine.filter({ hasText: first })).toContainText("결제 실패 1회");
  await expect(mine.filter({ hasText: second })).toContainText("멤버십 적용");
  const passes = participant.getByRole("list", { name: "내 이용권" });
  await expect(passes.getByRole("listitem")).toHaveCount(1);
  await expect(passes).toContainText("멤버십 1개월 · 이용 중");
  await expect(passes).toContainText("만료");
  for (const width of [360, 1440]) {
    await participant.setViewportSize({ width, height: 900 });
    expect(
      await participant.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }

  // An application after the membership expires needs a pass; pay later from its page.
  const later = await createSlot(operator, days + 45);
  await applyFor(participant, later);
  await participant.getByRole("button", { name: "신청 제출" }).click();
  await expect(participant.getByRole("status").first()).toContainText(
    "이용권 결제가 필요합니다",
  );
  await participant
    .getByRole("link", { name: "입력 상태", exact: true })
    .click();
  const pending = mine.filter({ hasText: later });
  await expect(pending).toContainText("결제: 결제 필요");
  await pending.getByRole("button", { name: "결제하기" }).click();
  await expect(participant).toHaveURL(/\/participant\/payment\/[0-9a-f-]+$/);
  await participant.reload();
  const payLater = participant.getByRole("region", { name: "모의 결제" });
  await payLater.getByRole("radio", { name: /^멤버십 1개월/ }).check();
  await payLater.getByRole("button", { name: "모의 결제하기" }).click();
  await expect(payLater.getByRole("alert")).toContainText(
    "후보 회차가 시작되기 전에 끝납니다",
  );

  await operator.goto("/admin/applications");
  const row = operator
    .getByRole("list", { name: "신청 목록" })
    .locator(":scope > li")
    .filter({ hasText: first });
  await expect(row).toContainText(account);
  await expect(row).toContainText("결제 완료");
  await expect(row.getByRole("button", { name: /결제/ })).toHaveCount(0);
  await operatorContext.close();
  await participantContext.close();
});
