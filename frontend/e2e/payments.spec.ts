import { test, expect, type Page } from "@playwright/test";
import { call, display, login, participantPassword } from "./support";

// The Playwright web server resets the local schema before seeding, so no earlier run's
// membership covers this run's applications.
const account = "participant-03";

async function createSlot(
  page: Page,
  daysAhead: number,
  closesInSeconds?: number,
) {
  const start = new Date(Date.now() + daysAhead * 86400_000);
  start.setUTCSeconds(0, 0);
  const iso = (offsetHours: number) =>
    new Date(start.getTime() + offsetHours * 3600_000).toISOString();
  const closes =
    closesInSeconds === undefined
      ? iso(-48)
      : new Date(Date.now() + closesInSeconds * 1000).toISOString();
  const body = await call(page, "POST", "/api/admin/event-slots", {
    region_code: "euljiro",
    starts_at: iso(0),
    ends_at: iso(2),
    closes_at: closes,
    matches_at: iso(-24),
    capacity: 12,
  });
  return {
    id: body.event_slot.id as string,
    name: display.format(new Date(body.event_slot.starts_at)),
    matches: display.format(new Date(body.event_slot.matches_at)),
  };
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
  // Random offsets keep slots apart from the other specs' slots; the first two fall
  // within one month.
  const days = 5 + Math.floor(Math.random() * 10) + Math.random();
  const operatorContext = await browser.newContext();
  const operator = await operatorContext.newPage();
  await login(operator, "operator", "synthetic-operator-password");
  const first = await createSlot(operator, days);
  const second = await createSlot(operator, days + 3);

  const participantContext = await browser.newContext();
  const participant = await participantContext.newPage();
  await login(participant, account, participantPassword);
  const initialPasses = await participant.request.get("/api/me/entitlements");
  expect(initialPasses.ok()).toBeTruthy();
  const initialPassCount = (await initialPasses.json()).entitlements.length;
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

  await applyFor(participant, first.name);
  const products = participant.getByRole("radiogroup", { name: "이용권" });
  await expect(products).toContainText("1회권 · 9,900원");
  await expect(products).toContainText("멤버십 6개월 · 120,000원");
  // Provisional U03 rules are marked as such where the product is chosen.
  await expect(products).toContainText("임시 적용 · 확정 전");
  await products.getByRole("radio", { name: /^1회권/ }).check();
  await participant.getByRole("button", { name: "신청 제출" }).click();

  // The mock payment step: clearly not a real charge, refund and no-show policy shown
  // before paying.
  const mock = participant.getByRole("region", { name: "모의 결제" });
  await expect(mock).toContainText("모의 결제 · 실제 결제가 발생하지 않습니다");
  await expect(mock).toContainText("화요일 24:00 이후 환불 불가");
  await expect(mock).toContainText("세부 환불 정책 미정");
  await expect(mock).toContainText("노쇼·취소 정책 미정");
  await expect(mock).toContainText("결제 금액 9,900원");
  await mock.getByRole("checkbox", { name: /실패 시뮬레이션/ }).check();
  await mock.getByRole("button", { name: "모의 결제하기" }).click();
  await expect(
    mock.getByRole("alert").filter({ hasText: "결제 실패" }),
  ).toBeVisible();
  await mock.getByRole("checkbox", { name: /실패 시뮬레이션/ }).uncheck();
  await mock.getByRole("radio", { name: /^멤버십 1개월/ }).check();
  await expect(mock).toContainText("결제 금액 35,000원");
  await mock.getByRole("button", { name: "모의 결제하기" }).click();
  await expect(
    mock.getByRole("status").filter({ hasText: "결제 완료" }),
  ).toBeVisible();

  // A second application inside the membership period needs no payment.
  await participant.getByRole("button", { name: "내 신청 보기" }).click();
  await applyFor(participant, second.name);
  await participant.getByRole("button", { name: "신청 제출" }).click();
  await expect(
    participant
      .getByRole("status")
      .filter({ hasText: "보유한 멤버십으로 결제 없이" }),
  ).toBeVisible();

  await participant
    .getByRole("link", { name: "입력 상태", exact: true })
    .click();
  const mine = participant
    .getByRole("list", { name: "내 신청" })
    .locator(":scope > li");
  const paid = mine.filter({ hasText: first.name });
  await expect(paid).toContainText("결제 완료");
  await expect(paid).toContainText("결제 실패 1회");
  // Application, payment and matching are separate status lines.
  await expect(paid).toContainText("신청: 신청 완료");
  await expect(paid).toContainText(
    `매칭: 매칭 대기 (WAITING) · 매칭 예정 ${first.matches}`,
  );
  await expect(mine.filter({ hasText: second.name })).toContainText(
    "멤버십 적용",
  );
  await expect(mine.filter({ hasText: second.name })).toContainText(
    "매칭: 매칭 대기 (WAITING)",
  );
  // The no-show policy is shown after submission too.
  await expect(participant.getByText(/노쇼·취소 정책 미정/)).toBeVisible();
  const passes = participant.getByRole("list", { name: "내 이용권" });
  await expect(passes.getByRole("listitem")).toHaveCount(initialPassCount + 1);
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
  await applyFor(participant, later.name);
  await participant.getByRole("button", { name: "신청 제출" }).click();
  await expect(
    participant
      .getByRole("status")
      .filter({ hasText: "이용권 결제가 필요합니다" }),
  ).toBeVisible();
  await participant
    .getByRole("link", { name: "입력 상태", exact: true })
    .click();
  const pending = mine.filter({ hasText: later.name });
  await expect(pending).toContainText("결제: 결제 필요");
  await expect(pending).toContainText("매칭: 결제 필요 · 미결제 시 매칭 제외");
  await pending.getByRole("button", { name: "결제하기" }).click();
  await expect(participant).toHaveURL(/\/participant\/payment\/[0-9a-f-]+$/);
  await participant.reload();
  const payLater = participant.getByRole("region", { name: "모의 결제" });
  await payLater.getByRole("radio", { name: /^멤버십 1개월/ }).check();
  await payLater.getByRole("button", { name: "모의 결제하기" }).click();
  await expect(
    payLater
      .getByRole("alert")
      .filter({ hasText: "후보 회차가 시작되기 전에 끝납니다" }),
  ).toBeVisible();
  // A single pass paid for an application that is then canceled stays held, tied to
  // the canceled application.
  await payLater.getByRole("radio", { name: /^1회권/ }).check();
  await payLater.getByRole("button", { name: "모의 결제하기" }).click();
  await expect(
    payLater.getByRole("status").filter({ hasText: "결제 완료" }),
  ).toBeVisible();
  await participant.getByRole("button", { name: "내 신청 보기" }).click();
  await pending.getByRole("button", { name: "신청 취소" }).click();
  await expect(pending).toContainText("신청: 신청 취소됨");
  await participant.reload();
  await expect(passes.getByRole("listitem")).toHaveCount(initialPassCount + 2);
  await expect(passes).toContainText("1회권 · 취소된 신청에 묶여 보유");

  // After the earliest candidate closes an unpaid application cannot be paid any more.
  const closing = await createSlot(operator, days + 50, 4);
  await call(participant, "POST", "/api/me/applications", {
    request_key: crypto.randomUUID(),
    event_slot_ids: [closing.id],
  });
  await participant.waitForTimeout(4500);
  await participant.reload();
  const closed = mine.filter({ hasText: closing.name });
  await expect(closed).toContainText("결제: 결제 마감 · 미결제");
  await expect(closed).toContainText("매칭: 미결제로 매칭 제외");
  await expect(closed.getByRole("button", { name: "결제하기" })).toHaveCount(0);

  await operator.goto("/admin/applications");
  const row = operator
    .getByRole("list", { name: "신청 목록" })
    .locator(":scope > li")
    .filter({ hasText: first.name });
  await expect(row).toContainText(account);
  await expect(row).toContainText("결제 완료");
  await expect(row).toContainText("매칭: 매칭 대기 (WAITING)");
  await expect(row.getByRole("button", { name: /결제/ })).toHaveCount(0);
  await operatorContext.close();
  await participantContext.close();
});
