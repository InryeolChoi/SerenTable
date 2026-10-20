import { test, expect } from "@playwright/test";
import { login } from "./support";

// Random offsets keep this spec's slots apart from the other specs' slots.
function seoulLocal(daysAhead: number, hour: number, minute: number) {
  const base = new Date(Date.now() + 9 * 3600_000 + daysAhead * 86400_000);
  const day = base.toISOString().slice(0, 10);
  return `${day}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

test("운영자가 만든 회차를 참가자가 서울 시각으로 확인한다", async ({
  browser,
}) => {
  const days = 30 + Math.floor(Math.random() * 300);
  const minute = Math.floor(Math.random() * 60);
  const operatorContext = await browser.newContext();
  const operator = await operatorContext.newPage();
  await login(operator, "operator", "synthetic-operator-password");
  await operator.getByRole("link", { name: "회차 관리", exact: true }).click();
  const form = operator.getByRole("form", { name: "회차 만들기" });
  await expect(form).toBeVisible();
  await form.getByLabel("지역").selectOption({ label: "을지로" });
  await form
    .getByLabel("시작 시각", { exact: true })
    .fill(seoulLocal(days, 19, minute));
  await form
    .getByLabel("종료 시각", { exact: true })
    .fill(seoulLocal(days, 21, minute));
  await form
    .getByLabel("신청 마감", { exact: true })
    .fill(seoulLocal(days, 15, minute));
  await form
    .getByLabel("매칭 예정", { exact: true })
    .fill(seoulLocal(days, 14, minute));
  await form.getByLabel("정원").fill("12");
  await form.getByRole("button", { name: "회차 만들기" }).click();
  // 입력 문제는 인라인 배너가 아니라 팝업으로 모아 알린다. 닫으면 입력은 그대로 남는다.
  const problems = operator.getByRole("dialog", {
    name: "입력을 확인해 주세요",
  });
  await expect(problems).toBeVisible();
  await expect(problems).toContainText("신청 마감 ≤ 매칭 예정 ≤ 시작 시각");
  await operator
    .getByRole("button", { name: "입력을 확인해 주세요 닫기", exact: true })
    .click();
  await expect(problems).not.toBeVisible();
  await expect(form.getByLabel("매칭 예정", { exact: true })).toBeFocused();
  await expect(form.getByLabel("정원")).toHaveValue("12");
  await form
    .getByLabel("매칭 예정", { exact: true })
    .fill(seoulLocal(days, 16, minute));
  await form.getByRole("button", { name: "회차 만들기" }).click();
  // The list reload that follows shows its own role=status loading notice, so a
  // page-wide status locator can resolve to two elements. Scope it to the confirmation.
  await expect(
    operator
      .getByRole("status")
      .filter({ hasText: "을지로 회차를 만들었습니다" }),
  ).toBeVisible();
  const time = `19:${String(minute).padStart(2, "0")}`;
  const created = operator
    .getByRole("list", { name: "회차 목록" })
    .getByRole("listitem")
    .filter({ hasText: "을지로" })
    .filter({ hasText: time });
  await expect(created).toHaveCount(1);
  await expect(created).toContainText("정원 12명");
  await expect(created).toContainText("모집 중");
  for (const width of [360, 1440]) {
    await operator.setViewportSize({ width, height: 900 });
    expect(
      await operator.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }

  await form.getByLabel("지역").selectOption({ label: "을지로" });
  await form
    .getByLabel("시작 시각", { exact: true })
    .fill(seoulLocal(days, 19, minute));
  await form
    .getByLabel("종료 시각", { exact: true })
    .fill(seoulLocal(days, 21, minute));
  await form
    .getByLabel("신청 마감", { exact: true })
    .fill(seoulLocal(days, 15, minute));
  await form
    .getByLabel("매칭 예정", { exact: true })
    .fill(seoulLocal(days, 16, minute));
  await form.getByRole("button", { name: "회차 만들기" }).click();
  await expect(
    operator
      .getByRole("alert")
      .filter({ hasText: "같은 지역·시작 시각의 회차가 이미 있습니다" }),
  ).toBeVisible();
  await operatorContext.close();

  const participantContext = await browser.newContext();
  const participant = await participantContext.newPage();
  await login(participant, "participant-01", "synthetic-participant-password");
  await participant
    .getByRole("link", { name: "모집 회차", exact: true })
    .click();
  const visible = participant
    .getByRole("list", { name: "모집 중인 회차" })
    .getByRole("listitem")
    .filter({ hasText: "을지로" })
    .filter({ hasText: time });
  await expect(visible).toHaveCount(1);
  await expect(visible).toContainText("정원 12명");
  for (const width of [360, 1440]) {
    await participant.setViewportSize({ width, height: 900 });
    expect(
      await participant.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
  await participant.goto("/admin/events");
  await expect(
    participant.getByRole("heading", { name: "접근 권한이 없습니다" }),
  ).toBeVisible();
  await participantContext.close();
});

test("지난 신청 마감과 정원 범위 오류도 같은 팝업으로 모아 알린다", async ({
  page,
}) => {
  const days = 30 + Math.floor(Math.random() * 300);
  await login(page, "operator", "synthetic-operator-password");
  await page.getByRole("link", { name: "회차 관리", exact: true }).click();
  const form = page.getByRole("form", { name: "회차 만들기" });
  await form.getByLabel("지역").selectOption({ label: "을지로" });
  await form.getByLabel("시작 시각", { exact: true }).fill(seoulLocal(days, 19, 0));
  await form.getByLabel("종료 시각", { exact: true }).fill(seoulLocal(days, 21, 0));
  await form.getByLabel("신청 마감", { exact: true }).fill(seoulLocal(-1, 15, 0));
  await form.getByLabel("매칭 예정", { exact: true }).fill(seoulLocal(days, 16, 0));
  await form.getByLabel("정원").fill("3");
  await form.getByRole("button", { name: "회차 만들기" }).click();
  const problems = page.getByRole("dialog", { name: "입력을 확인해 주세요" });
  await expect(problems).toContainText("정원은 4~100명 사이의 정수여야 합니다.");
  await expect(problems).toContainText("신청 마감은 지금 이후여야 합니다.");
  await page.keyboard.press("Escape");
  await expect(problems).not.toBeVisible();
  await expect(form.getByLabel("정원")).toBeFocused();
  await expect(form.getByLabel("신청 마감", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );

  // 화면 검사를 지난 뒤 서버가 거절해도(제출 사이 마감 경과 등) 같은 팝업과 필드로 안내한다.
  await form.getByLabel("정원").fill("12");
  await form.getByLabel("신청 마감", { exact: true }).fill(seoulLocal(days, 15, 0));
  await page.route("**/api/admin/event-slots", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({
            detail: [
              {
                type: "closes_in_past",
                loc: ["body", "closes_at"],
                msg: "closes_in_past",
              },
            ],
          }),
        })
      : route.continue(),
  );
  await form.getByRole("button", { name: "회차 만들기" }).click();
  await expect(problems).toContainText("신청 마감은 지금 이후여야 합니다.");
  await page
    .getByRole("button", { name: "입력을 확인해 주세요 닫기", exact: true })
    .click();
  await expect(form.getByLabel("신청 마감", { exact: true })).toBeFocused();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
