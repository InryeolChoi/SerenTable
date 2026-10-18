import { execFileSync } from "node:child_process";
import { test, expect } from "@playwright/test";
import { call, display, login, operatorPassword, participantPassword } from "./support";

function refundFault(enabled: boolean) {
  // Only the dedicated local browser DB may receive this storage-fault fixture.
  execFileSync("uv", ["run", "python", "-c", `
import os
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
url=make_url(os.environ['DATABASE_URL'])
assert url.host in ('127.0.0.1','localhost') and url.database in ('serentable_test','serentable_test_w9_recovery_e2e')
with create_engine(url.set(drivername='postgresql+psycopg')).begin() as c:
 c.execute(text("DROP TRIGGER IF EXISTS browser_refund_fault ON mock_refund_event"))
 c.execute(text("DROP FUNCTION IF EXISTS browser_refund_fault()"))
 ${enabled ? `c.execute(text("CREATE FUNCTION browser_refund_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic storage failure' USING ERRCODE='23514'; END $$"))
 c.execute(text("CREATE TRIGGER browser_refund_fault BEFORE INSERT ON mock_refund_event FOR EACH ROW EXECUTE FUNCTION browser_refund_fault()"))` : ""}
`], { cwd: "..", env: { ...process.env, PYTHONPATH: "backend" } });
}

test("모의 환불 실패를 참가자에게 정확히 표시하고 운영자가 한 번 재시도한다", async ({ browser }) => {
  test.setTimeout(90000);
  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  const [participant, operator] = await Promise.all(contexts.map(c => c.newPage()));
  let faultInstalled = false;
  try {
    await login(participant, "participant-01", participantPassword);
    await login(operator, "operator", operatorPassword);
    await call(participant, "PUT", "/api/me/profile", {
      name: "합성 이름", display_name: "환불 검증 참가자", contact: "010-0000-0000",
      instagram_id: "synthetic_refund", birth_year: 1995, gender: "기록한 성별",
      occupation: "합성 직업", interests: ["reading"], self_traits: ["listener"],
      desired_traits: ["similar"], meal_budget_bands: ["10000_20000"],
    });
    await call(participant, "PUT", "/api/me/consents", { consents: ["privacy", "operation"].map(purpose => ({ purpose, version: "demo-2026-10-16", accepted: true })) });
    const start = Date.now() + 120 * 86400000;
    const close = Date.now() + 6000;
    const { event_slot: slot } = await call(operator, "POST", "/api/admin/event-slots", {
      region_code: "hongdae", starts_at: new Date(start).toISOString(),
      ends_at: new Date(start + 7200000).toISOString(), closes_at: new Date(close).toISOString(),
      matches_at: new Date(close + 500).toISOString(), capacity: 12,
    });
    const { application } = await call(participant, "POST", "/api/me/applications", { request_key: crypto.randomUUID(), event_slot_ids: [slot.id] });
    await call(participant, "POST", `/api/me/applications/${application.id}/payments`, { request_key: crypto.randomUUID(), product_code: "single", simulate_failure: false });
    await operator.waitForTimeout(Math.max(0, close + 700 - Date.now()));
    execFileSync("uv", ["run", "python", "-m", "serentable.worker", "--once"], { cwd: "..", env: { ...process.env, PYTHONPATH: "backend" } });
    await participant.goto("/participant");
    const card = participant.getByRole("list", { name: "내 신청" }).locator(":scope > li").filter({ hasText: display.format(new Date(start)) });
    await card.getByRole("button", { name: "다른 일정 확인" }).click();
    refundFault(true); faultInstalled = true;
    await card.getByRole("button", { name: "1회권 전액 모의 환불", exact: true }).click();
    await expect(card).toContainText("운영자 재시도 대기");
    await expect(card).not.toContainText("전액 모의 환불 완료");
    refundFault(false); faultInstalled = false;
    await operator.goto("/admin/console");
    const exception = operator.locator("article").filter({ has: operator.getByRole("heading", { name: "모의 환불 실패 · 처리 대기" }) }).filter({ hasText: slot.id.slice(0, 8) });
    await expect(exception).toContainText("9,900원");
    await exception.getByRole("button", { name: "모의 환불 재시도", exact: true }).click();
    await expect(exception).toHaveCount(0);
    await participant.reload();
    const result = participant.getByRole("list", { name: "내 신청" }).locator(":scope > li").filter({ hasText: display.format(new Date(start)) });
    await result.getByText("실패 해결 이력", { exact: true }).click();
    await expect(result).toContainText("전액 모의 환불 완료");
    await expect(result.getByRole("list", { name: "모의 환불 처리 이력" }).locator("li")).toHaveCount(3);
  } finally {
    if (faultInstalled) refundFault(false);
    await Promise.all(contexts.map(c => c.close()));
  }
});
