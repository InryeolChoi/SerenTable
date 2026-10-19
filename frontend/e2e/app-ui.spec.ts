import { test, expect } from "@playwright/test";
import { login, participantPassword } from "./support";

test("참가자는 현재 화면을 구분하고 작은 화면에서도 주요 메뉴를 누를 수 있다", async ({
  page,
}) => {
  await login(page, "participant-01", participantPassword);
  const navigation = page.getByRole("navigation", {
    name: "주요 화면",
    exact: true,
  });
  await expect(navigation.locator('[aria-current="page"]')).toHaveCount(1);
  for (const width of [320, 344, 601, 744, 834, 1366]) {
    await page.setViewportSize({ width, height: 1000 });
    const targets = await navigation
      .locator("a, button")
      .evaluateAll((elements) =>
        elements
          .filter((element) => element.getBoundingClientRect().width > 0)
          .map((element) => ({
            width: element.getBoundingClientRect().width,
            height: element.getBoundingClientRect().height,
          })),
      );
    expect(targets.length).toBeGreaterThan(0);
    for (const target of targets) {
      expect(target.width).toBeGreaterThanOrEqual(44);
      expect(target.height).toBeGreaterThanOrEqual(44);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
});

test("참가자는 알림을 필요할 때 열고 닫아 원래 작업으로 돌아온다", async ({
  page,
}) => {
  await login(page, "participant-01", participantPassword);
  const trigger = page.getByRole("button", { name: "알림", exact: true });
  await expect(trigger).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "내 식탁 준비", exact: true }),
  ).toBeInViewport();
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "알림", exact: true });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "이 기기 푸시 허용" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test("데이터 응답을 기다려도 화면 이동은 즉시 보이며 접고 펼쳐도 입력이 유지된다", async ({
  page,
}) => {
  await login(page, "participant-01", participantPassword);
  let resume!: () => void;
  const gate = new Promise<void>((resolve) => {
    resume = resolve;
  });
  await page.route("**/api/me/profile", async (route) => {
    await gate;
    await route.continue();
  });
  await page.getByRole("button", { name: "더보기", exact: true }).click();
  await page
    .getByRole("dialog", { name: "더보기", exact: true })
    .getByRole("link", { name: /^프로필/ })
    .click();
  try {
    await expect(
      page.getByRole("heading", { name: "내 프로필", exact: true }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "프로필을 확인하고 있습니다" }),
    ).toBeVisible();
  } finally {
    resume();
  }
  await page
    .getByRole("form", { name: "본인 프로필" })
    .getByLabel("표시명")
    .fill("접었다 펼쳐도 유지할 합성 입력");
  for (const width of [344, 744, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.getByLabel("표시명")).toHaveValue(
      "접었다 펼쳐도 유지할 합성 입력",
    );
  }
});

test("운영 화면을 늦게 불러와도 준비 상태를 보여주고 실제 제목으로 포커스를 넘긴다", async ({
  page,
}) => {
  await login(page, "operator", "synthetic-operator-password");
  let resume!: () => void;
  const gate = new Promise<void>((resolve) => {
    resume = resolve;
  });
  await page.route("**/assets/console-*.js", async (route) => {
    await gate;
    await route.continue();
  });
  await page.getByRole("link", { name: "운영 현황", exact: true }).click();
  const waiting = page
    .getByRole("status")
    .filter({ hasText: "운영 화면을 준비하고 있습니다" });
  try {
    await expect(waiting).toBeVisible();
  } finally {
    resume();
  }
  await expect(waiting).not.toBeVisible();
  await expect(
    page.getByRole("heading", { name: "운영 현황", exact: true }),
  ).toBeFocused();
  await expect(page).toHaveTitle("운영 현황 · 우연한 식탁");
});

test("알림을 닫았다 다시 열어도 이 기기에서 확인한 푸시 안내를 잃지 않는다", async ({
  page,
}) => {
  await login(page, "participant-01", participantPassword);
  const trigger = page.getByRole("button", { name: "알림", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "알림", exact: true });
  await dialog.getByRole("button", { name: "이 기기 푸시 허용" }).click();
  const status = dialog.getByRole("status");
  await expect(status).toContainText(
    /서버 푸시 설정이 준비되지|이 환경은 푸시를 지원하지/,
  );
  const message = await status.textContent();
  await dialog.getByRole("button", { name: "알림 닫기" }).click();
  await trigger.click();
  await expect(dialog.getByRole("status")).toHaveText(message!);
});

test("운영 화면 파일을 받지 못해도 다른 메뉴로 이동할 수 있다", async ({
  page,
}) => {
  await login(page, "operator", "synthetic-operator-password");
  await page.route("**/assets/console-*.js", (route) => route.abort("failed"));
  await page.getByRole("link", { name: "운영 현황", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "화면을 불러오지 못했습니다" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "화면 새로고침", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "참가자 관리", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 참가자 관리", exact: true }),
  ).toBeVisible();
});

test("목록과 달력을 전환해 가능한 날짜의 회차를 고르고 선택을 유지한다", async ({
  browser,
}) => {
  const { call, operatorPassword, openScreen } = await import("./support");
  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  await login(admin, "operator", operatorPassword);
  // Fixed Seoul date on the first day of a future month checks UTC/date boundaries.
  const year = new Date().getUTCFullYear() + 1;
  await call(admin, "POST", "/api/admin/event-slots", {
    region_code: "hongdae",
    starts_at: `${year}-03-01T00:30:00+09:00`,
    ends_at: `${year}-03-01T02:30:00+09:00`,
    closes_at: `${year}-02-27T00:00:00+09:00`,
    matches_at: `${year}-02-28T00:00:00+09:00`,
    capacity: 12,
  });
  const context = await browser.newContext();
  const page = await context.newPage();
  await login(page, "participant-01", participantPassword);
  await openScreen(page, "일정 신청");
  await page.getByRole("button", { name: "달력 보기", exact: true }).click();
  // The calendar initially shows the earliest offered month; navigate forward as needed.
  for (
    let i = 0;
    i < 24 &&
    !(await page
      .getByRole("button", {
        name: `${year}년 3월 1일, 회차 있음`,
        exact: true,
      })
      .count());
    i++
  ) {
    await page.getByRole("button", { name: "다음 달", exact: true }).click();
  }
  const day = page.getByRole("button", {
    name: `${year}년 3월 1일, 회차 있음`,
    exact: true,
  });
  const dayBefore = await day.boundingBox();
  await day.click();
  const bubble = page.getByRole("region", {
    name: "선택한 날짜의 회차",
    exact: true,
  });
  await expect(bubble).toContainText("홍대");
  const dateBox = await day.boundingBox();
  const bubbleBox = await bubble.boundingBox();
  expect(Math.abs(dateBox!.y - dayBefore!.y)).toBeLessThan(1);
  // A first-row date opens below itself so the view switch above the grid stays usable.
  const gap = bubbleBox!.y - (dateBox!.y + dateBox!.height);
  expect(gap).toBeGreaterThanOrEqual(8);
  expect(gap).toBeLessThanOrEqual(16);
  await expect(page.getByRole("button", { name: "목록 보기", exact: true })).toBeVisible();
  expect(bubbleBox!.x).toBeGreaterThanOrEqual(0);
  expect(bubbleBox!.x + bubbleBox!.width).toBeLessThanOrEqual(390);

  const choice = bubble.getByRole("checkbox");
  await choice.check();
  await page.getByRole("button", { name: "목록 보기", exact: true }).click();
  await expect(page.locator('input[type="checkbox"]:checked')).toHaveCount(1);
  await page.getByRole("button", { name: "달력 보기", exact: true }).click();
  await expect(bubble.getByRole("checkbox")).toBeChecked();
  const switcher = page.getByRole("group", { name: "회차 보기 방식" });
  await switcher.evaluate((element) => {
    // WebKit cannot construct Touch directly. Dispatch its public event shape.
    const start = new Event("touchstart", { bubbles: true });
    Object.defineProperty(start, "touches", { value: [{ clientX: 20 }] });
    element.dispatchEvent(start);
    const end = new Event("touchend", { bubbles: true });
    Object.defineProperty(end, "changedTouches", { value: [{ clientX: 100 }] });
    element.dispatchEvent(end);
  });
  await expect(
    page.getByRole("button", { name: "목록 보기", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "달력 보기", exact: true }).click();
  const disabled = page.locator(".calendar-days button:disabled");
  expect(await disabled.count()).toBeGreaterThan(0);
  await page.setViewportSize({ width: 320, height: 740 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await context.close();
  await adminContext.close();
});

test("운영자 회차 필터와 새로 고침은 작은 화면에서도 떨어져 배치된다", async ({
  page,
}) => {
  const { operatorPassword, openScreen } = await import("./support");
  await login(page, "operator", operatorPassword);
  await openScreen(page, "운영 현황");
  const section = page
    .locator("section")
    .filter({
      has: page.getByRole("heading", { name: "회차별 현황", exact: true }),
    })
    .last();
  for (const width of [320, 601, 834]) {
    await page.setViewportSize({ width, height: 900 });
    const select = await section.getByRole("combobox").boundingBox();
    const refresh = await section
      .getByRole("button", { name: "새로 고침", exact: true })
      .boundingBox();
    expect(select).not.toBeNull();
    expect(refresh).not.toBeNull();
    const xGap = Math.max(
      refresh!.x - (select!.x + select!.width),
      select!.x - (refresh!.x + refresh!.width),
    );
    const yGap = Math.max(
      refresh!.y - (select!.y + select!.height),
      select!.y - (refresh!.y + refresh!.height),
    );
    expect(Math.max(xGap, yGap)).toBeGreaterThanOrEqual(15);
  }
});
