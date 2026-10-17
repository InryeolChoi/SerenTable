import { execFileSync } from "node:child_process";
import { test, expect, type Page } from "@playwright/test";
import { call, login, participantPassword, operatorPassword } from "./support";

function isolatedClock(slot: string, ended: boolean) {
  // This is an isolated local fixture, never an API or production clock override.
  execFileSync("uv", ["run", "python", "-c", `
import os
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
url=make_url(os.environ['DATABASE_URL'])
assert url.host in ('127.0.0.1','localhost') and url.database in ('serentable_test','serentable_w89_e2e_test')
with create_engine(url.set(drivername='postgresql+psycopg')).begin() as c:
 c.execute(text("UPDATE event_slot SET closes_at=now()-interval '4 hours', matches_at=now()-interval '3 hours', starts_at=now()-interval '2 hours', ends_at=now()+interval '${ended ? '-1' : '30'} minutes' WHERE id=:id"), {'id':'${slot}'})
`], { cwd: "..", env: {...process.env, PYTHONPATH: "backend"} });
}
async function ready(page: Page, index: number) {
  await login(page, `participant-0${index}`, participantPassword);
  await call(page,"PUT","/api/me/profile", {
    name:"합성 이름", display_name:`검증 식탁 ${index}`, contact:"010-0000-0000",
    instagram_id:`synthetic_feedback_${index}`, birth_year:1995, gender:"기록한 성별",
    occupation:"합성 직업", interests:["reading"], self_traits:["listener"],
    desired_traits:["similar"], meal_budget_bands:["10000_20000"],
  });
  await call(page,"PUT","/api/me/consents", {consents:["privacy","operation"].map(purpose => ({purpose,version:"demo-2026-10-16",accepted:true}))});
}

test("참가 이력에서 체크인·평가하고 운영 현황에서 예외·감사·CSV를 확인한다", async ({browser}) => {
  test.setTimeout(90000);
  const contexts = await Promise.all(Array.from({length:5}, () => browser.newContext()));
  try {
    const pages = await Promise.all(contexts.map(c => c.newPage()));
    const [operator, ...members] = pages;
    await login(operator,"operator",operatorPassword);
    for (let i=0;i<4;i++) await ready(members[i],i+1);
    const start = Date.now()+75*86400000;
    const close = Date.now()+8000;
    const {event_slot:slot} = await call(operator,"POST","/api/admin/event-slots", {
      region_code:"euljiro", starts_at:new Date(start).toISOString(),
      ends_at:new Date(start+7200000).toISOString(), closes_at:new Date(close).toISOString(),
      matches_at:new Date(close+500).toISOString(), capacity:12,
    });
    for (const member of members) {
      const {application} = await call(member,"POST","/api/me/applications",{request_key:crypto.randomUUID(),event_slot_ids:[slot.id]});
      await call(member,"POST",`/api/me/applications/${application.id}/payments`,{request_key:crypto.randomUUID(),product_code:"single",simulate_failure:false});
    }
    await operator.waitForTimeout(Math.max(0,close+700-Date.now()));
    execFileSync("uv",["run","python","-m","serentable.worker","--once"],{cwd:"..",env:{...process.env,PYTHONPATH:"backend"}});
    isolatedClock(slot.id,false);
    await members[0].goto("/participant/history");
    const card = members[0].locator("article").filter({has:members[0].getByRole("button",{name:"도착 체크인"})});
    await card.getByRole("button",{name:"도착 체크인"}).click();
    await expect(members[0].getByRole("status").filter({hasText:"체크인 완료"})).toBeVisible();
    isolatedClock(slot.id,true);
    await members[0].reload();
    const evaluation = members[0].getByRole("region",{name:"모임 평가"});
    await expect(evaluation).toBeVisible();
    for (const label of ["테이블 전체 만족도","대화 만족도","식당 만족도","재참여 의향","추천 의향"])
      await evaluation.getByLabel(label).selectOption("4");
    await evaluation.getByRole("button",{name:"평가 저장",exact:true}).click();
    await expect(evaluation.getByText(/평가를 저장했습니다/)).toBeVisible();
    await members[0].reload();
    await expect(members[0].getByRole("button",{name:"평가 수정"})).toBeVisible();
    await operator.goto("/admin/console");
    await expect(operator.getByRole("heading",{name:"회차별 현황"})).toBeVisible();
    const exception = operator.locator("article").filter({has:operator.getByRole("heading",{name:"식당 배정 부족 · 처리 대기"})}).filter({hasText:slot.id.slice(0,8)});
    await exception.getByLabel(/처리 메모/).fill("격리 시연의 식당 부족을 확인했습니다.");
    await exception.getByRole("button",{name:"처리 결과 기록"}).click();
    await expect(exception).toHaveCount(0);
    const csv = await operator.request.get(`/api/admin/exports/tables.csv?event_slot_id=${slot.id}`);
    expect(csv.ok()).toBeTruthy(); expect(csv.headers()["content-disposition"]).toContain("attachment");
    expect(await csv.text()).toContain("검증 식탁 1");
    await operator.reload();
    await expect(operator.getByRole("heading",{name:"감사 이력"})).toBeVisible();
    await expect(operator.getByText("격리 시연의 식당 부족을 확인했습니다.",{exact:false})).toBeVisible();
    await members[0].goto("/admin/console");
    await expect(members[0].getByRole("heading",{name:"접근 권한이 없습니다"})).toBeVisible();
  } finally {await Promise.all(contexts.map(c => c.close()));}
});
