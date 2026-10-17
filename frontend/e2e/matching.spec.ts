import { execFileSync } from "node:child_process";
import { test, expect, devices, type Page } from "@playwright/test";
import { call, display, login, participantPassword } from "./support";

// The accounts the seed creates; a table needs at least four of them.
const members = ["participant-01", "participant-02", "participant-03", "participant-04"];

/** Run the separate runner once. It is the only way matching starts (MAT-01). */
function runMatchingWorker() {
  execFileSync(
    "uv",
    ["run", "python", "-m", "serentable.worker", "--once"],
    { cwd: "..", env: { ...process.env, PYTHONPATH: "backend" }, stdio: "inherit" },
  );
}

async function createSlot(
  page: Page,
  daysAhead: number,
  region: string,
  closesInSeconds: number,
) {
  const start = new Date(Date.now() + daysAhead * 86400_000);
  start.setUTCSeconds(0, 0);
  const closesAt = Date.now() + closesInSeconds * 1000;
  const body = await call(page, "POST", "/api/admin/event-slots", {
    region_code: region,
    starts_at: start.toISOString(),
    ends_at: new Date(start.getTime() + 2 * 3600_000).toISOString(),
    closes_at: new Date(closesAt).toISOString(),
    // Matching time is just after the close; that is what the runner waits for.
    matches_at: new Date(closesAt + 500).toISOString(),
    capacity: 12,
  });
  return {
    id: body.event_slot.id as string,
    name: display.format(start),
    matchesAt: closesAt + 500,
  };
}

async function prepare(page: Page, loginId: string, birthYear: number) {
  await login(page, loginId, participantPassword);
  await call(page, "PUT", "/api/me/profile", {
    name: "합성 이름",
    display_name: `매칭 식탁 ${loginId.slice(-2)}`,
    contact: "010-0000-0000",
    instagram_id: `synthetic_match_${loginId.slice(-2)}`,
    birth_year: birthYear,
    gender: "기록한 성별",
    occupation: "합성 직업",
    interests: ["music"],
    self_traits: ["listener"],
    desired_traits: ["similar"],
    meal_budget_bands: ["20000_30000"],
  });
  await call(page, "PUT", "/api/me/consents", {
    consents: [
      { purpose: "privacy", version: "demo-2026-10-16", accepted: true },
      { purpose: "operation", version: "demo-2026-10-16", accepted: true },
    ],
  });
}

/** Submit and pay through the API so the whole set fits inside the closing window. */
async function submitAndPay(page: Page, slotId: string) {
  const created = await call(page, "POST", "/api/me/applications", {
    request_key: crypto.randomUUID(),
    event_slot_ids: [slotId],
  });
  const applicationId = created.application.id as string;
  await call(page, "POST", `/api/me/applications/${applicationId}/payments`, {
    request_key: crypto.randomUUID(),
    product_code: "single",
    simulate_failure: false,
  });
}

/** Reload the status screen: login landed on it already, so a link click would not refetch. */
async function openMyApplications(page: Page) {
  await page.goto("/participant");
  await expect(
    page.getByRole("heading", { name: "내 식탁 준비" }),
  ).toBeVisible();
  return page.getByRole("list", { name: "내 신청" }).locator(":scope > li");
}

test("마감된 회차가 운영자 개입 없이 매칭되어 참가자와 운영자 화면에 결과가 보인다", async ({
  browser,
}, testInfo) => {
  const closeInSeconds = 15;
  const operatorContext = await browser.newContext({ ...devices["Pixel 7"] });
  const operator = await operatorContext.newPage();
  await login(operator, "operator", "synthetic-operator-password");

  const participantContexts = await Promise.all(
    members.map(() => browser.newContext({ ...devices["Pixel 7"] })),
  );
  const participants = await Promise.all(
    participantContexts.map((context) => context.newPage()),
  );
  // Profiles and consents first, so only the submissions sit inside the closing window.
  for (const [index, participant] of participants.entries())
    await prepare(participant, members[index], 1994 + index);

  const full = await createSlot(operator, 45 + Math.random(), "hongdae", closeInSeconds);
  const partial = await createSlot(operator, 52 + Math.random(), "gangnam", closeInSeconds);
  const alternative = await createSlot(operator, 60 + Math.random(), "euljiro", 3600);
  for (const participant of participants) await submitAndPay(participant, full.id);
  // Only three applications here: fewer people than a table needs.
  for (const participant of participants.slice(0, 3))
    await submitAndPay(participant, partial.id);

  // Wait for both slots' matching times to pass, then run the runner once.
  const remaining = full.matchesAt + 1000 - Date.now();
  await operator.waitForTimeout(Math.max(0, remaining));
  runMatchingWorker();

  const mine = await openMyApplications(participants[0]);
  const confirmed = mine.filter({ hasText: full.name });
  await expect(confirmed).toContainText("매칭: 매칭 확정 (CONFIRMED)");
  await expect(confirmed).toContainText("같은 테이블 4명");
  const passes = participants[0].getByRole("list", { name: "내 이용권" });
  await expect(passes.getByText("1회권 · 사용 완료", { exact: true })).toBeVisible();
  await expect(confirmed).toContainText("같은 식탁 소개:");
  for (const suffix of ["01", "02", "03", "04"])
    await expect(confirmed).toContainText(`매칭 식탁 ${suffix}`);
  // MAT-12: tablemates appear by display name only, never by contact or Instagram ID.
  const statusText = await participants[0].locator("main").innerText();
  expect(statusText).not.toContain("010-0000-0000");
  for (const suffix of ["02", "03", "04"])
    expect(statusText).not.toContain(`synthetic_match_${suffix}`);
  await confirmed.screenshot({ path: testInfo.outputPath("matching-confirmed-mobile.png") });
  // A slot the runner left out says why, instead of staying "waiting" forever.
  await expect(mine.filter({ hasText: partial.name })).toContainText(
    "매칭: 매칭 실패 · 대안 선택 대기 (ALTERNATIVE_OFFERED) · 함께 앉을 인원이 부족합니다",
  );
  const unseated = mine.filter({ hasText: partial.name });
  await unseated.getByRole("button", { name: "다른 일정 확인" }).click();
  const suggestions = unseated.getByRole("region", { name: "대체 일정" });
  await expect(suggestions).toContainText(alternative.name);
  await expect(suggestions).toContainText("조회만으로 일정이나 결제가 변경되지 않습니다");
  expect(await participants[0].evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await unseated.screenshot({ path: testInfo.outputPath("matching-alternatives-mobile.png") });
  // Every seated participant sees the same confirmation.
  for (const participant of participants.slice(1)) {
    const rows = await openMyApplications(participant);
    await expect(rows.filter({ hasText: full.name })).toContainText(
      "매칭 확정 (CONFIRMED)",
    );
  }

  // The operator history explains what the runner decided, read-only.
  await operator.goto("/admin/applications");
  const history = operator
    .getByRole("list", { name: "매칭 이력 목록" })
    .locator(":scope > li");
  const run = history.filter({ hasText: full.name });
  await expect(run).toContainText("확정 4명");
  // ADR-0011: years 1994..1997 (age 62.5), shared interest 100, "similar" to the same
  // self trait 100, all new 100; gender and MBTI cannot be computed.
  // (.25*62.5 + .15*100 + .10*100 + .15*100) / .65 = 85.58
  await expect(run).toContainText("최소 점수 50");
  await expect(run).toContainText("테이블 점수 85.58");
  await expect(run).toContainText("participant-01");
  await expect(history.filter({ hasText: partial.name })).toContainText(
    "확정 0명",
  );
  for (const width of [360, 1440]) {
    await operator.setViewportSize({ width, height: 900 });
    expect(
      await operator.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
  for (const context of participantContexts) await context.close();
  await operatorContext.close();
});
