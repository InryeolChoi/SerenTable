# 도구 간 작업 인계

마지막 기록: 2026-10-17 01:20 KST. Codex·Claude Code 및 다른 개발 에이전트가 도구 전환 시 읽는 공통 상태 기록이다. 아래 내용은 해당 시점의 스냅샷이며 시작 시 Git·GitHub·배포 상태를 재확인한다.

## 먼저 확인할 현재 상태

- **2026-10-17 Codex 재개·구현 검토:** `codex/work6-matching-runner`에서 기존 PR #31을 보완한다. 사용자 AGENTS.md/미추적 설정·스크립트를 보존했다. [검토·수정·검증·Blaybus 기록](../design/implementation-review-2026-10-17.md)을 우선 확인한다. 아래 그리디 제한·파일명 순서 우회·소개 미구현 설명은 후속 수정으로 대체된다. `73acf66` pytest121/브라우저10 통과, 후속 FK 교착 회귀2건도 수정 후 통과. 최종 head CI는 PR #31에서 확인한다. Work #6은 미완료이며 CEO의 U03/U04 답변은 아직 없다는 사용자 확인을 받았다. 새 운영 배포·실기기·100명 DB 검증은 수행하지 않았다.

- **Work #6 예약 매칭: ①-a 계약 승인·①-b 자동 실행기(2026-10-17, OpenRouter DeepSeek 세션, Claude Code 도구):** 사용자가 2026-10-17 승인한 계약 [PR #30](https://github.com/InryeolChoi/SerenTable/pull/30)(`docs/design/matching-contract.md`, 초안, CI SUCCESS, **사용자 머지 대기**, Task 4단계 분할·U06 배정·U07 소유권)을 실제로 실행하는 자동 실행기를 브랜치 `codex/work6-matching-runner`(origin/main `6d707cb` 기준, HEAD `d15cd78`)에 구현해 [PR #31](https://github.com/InryeolChoi/SerenTable/pull/31) → main(열림, Refs #6)으로 올렸다. CI [38929034129](https://github.com/InryeolChoi/SerenTable/actions/runs/38929034129) **SUCCESS**. 구현: `backend/serentable/matching.py`(하드 제약 플래너 + 회차별 트랜잭션 실행기 + 읽기 전용 운영자 이력), `migrations/versions/0007_matching.py`(match_run·dining_table·table_assignment·match_run_member·match_participation, 부분 유니크 인덱스 2종), `worker.py` 루프가 유일한 트리거(MAT-01, 공개 트리거·운영자 시작 없음), `applications.py`·`main.py` 노출, 프런트 `api.ts`·`applications.tsx` 읽기 전용 화면, `tests/test_matching_runner.py`(10건), `frontend/e2e/reserved-matching.spec.ts`. 규칙: 하드 제약만·앉는 인원 최대화·제출 순서 tie-break(U06), 신청당 살아 있는 배치 하나·`matches_at` 오름차순(U07), 회차 `FOR UPDATE` + 잠금 뒤 DB 시계, 중단 세대 ABANDONED → attempt+1, 동시 실행은 부분 유니크가 1개만 통과, 확정은 ①-b에서 최종(U13 미결정), 매칭 축은 `match_participation`(application.state 불변). 로컬 검증(실제 PG17 컨테이너 55432): pytest **115 passed**(이전 105 회귀 없음), ruff check/format(CI 범위) PASS, `npm run build` PASS, Playwright 전체 **10/10**(webServer가 스키마 재생성, 실행기 로그 `worker_matching_ok runs=2`), 마이그레이션 0007 up/down 왕복. 전체 스위트 첫 실행에서 `payments.spec.ts:147`이 이용권 1개를 기대했는데 **3개**를 잡아 실패했고, 원인을 실측으로 확인했다(같은 DB를 공유하는데 이 스펙이 participant-03의 1회권을 2장 사서 1→3). 로직은 바꾸지 않고 스펙 파일명을 `reserved-matching.spec.ts`로 바꿔 participant-03의 개수를 절대값으로 단언하는 `payments.spec.ts` 뒤에 실행되게 하고 이유를 파일에 적었다. **미완료:** Task ①-c(미매칭 대안·이동/보관/환불), U05 점수 도입, 배포 환경 실행기 동작·브라우저 E2E, 실행 규모(U19·100명), 계약 문서 76행 `UNIQUE(application_id)` → `WHERE ended_at IS NULL` 부분 유니크 문장 정정(#30 머지 후). Work #6은 부분 완료이므로 열어 둔다. 미커밋 제품 변경 없음(사용자 변경 `AGENTS.md` 수정과 미추적 `.claude/`·`.codex/`·`scripts/claude-deepseek.sh`·`scripts/claude-glm.sh`는 커밋하지 않음). 계약 PR #30은 head `4e40fa2`, CI [38925499068](https://github.com/InryeolChoi/SerenTable/actions/runs/38925499068) SUCCESS, 초안 상태로 **사용자 머지 대기**이며 이 브랜치에는 계약 문서가 없다. Issue [#6](https://github.com/InryeolChoi/SerenTable/issues/6)은 열려 있고 체크박스는 사용자가 갱신한다. **다음 작업:** 사용자 리뷰·머지(#30 → #31 순서 권장), 그 뒤 ①-c(미매칭 대안·이동/보관/환불)를 별도 브랜치로 착수, 머지 후 계약 76행 문장과 [운영 지침](../operations/foundation-runbook.md) 110행의 "worker는 예약 매칭 엔진 미구현" 서술을 갱신. 독립 검증 방법은 아래 인계 절을 따른다.
- **Work #4 Task ③ E2E 알림 단언 규약 정리(2026-10-17, OpenRouter DeepSeek 세션, Claude Code 도구):** PR [#27](https://github.com/InryeolChoi/SerenTable/pull/27)이 사용자에 의해 main에 **병합**되었고(merge `05287e2`, 2026-10-16T14:36:13Z, 원격 브랜치 삭제), main 기준 새 브랜치 `codex/work4-task3-notice-assertions`에서 남아 있던 같은 패턴을 정리해 PR [#28](https://github.com/InryeolChoi/SerenTable/pull/28)(열림, Refs #4)을 올렸다. 화면 전역 `getByRole("status")`/`getByRole("alert")` 단언을 **문구나 알림을 담은 한 영역**으로 좁혔고(`applications`·`events`·`payments`·`shell` specs 적용, `payments`의 `.first()` 우회 제거), 규약은 `frontend/e2e/support.ts`에 기록했다. 부정 단언(`not.toContainText`)은 문구 filter로 좁히면 무의미해지므로 로그인 폼 영역으로 좁혔다. **테스트 전용 변경**이며 제품 화면·API·정책·마이그레이션은 바꾸지 않았다. 실측 근거: 세션 철회 뒤 로그인 화면에서 화면 전역 alert locator가 2개를 잡아 `toContainText`가 strict mode로 실패하고, 폼으로 좁힌 locator는 1개를 잡아 통과(임시 진단 스펙은 실행 후 삭제, 커밋하지 않음). 로컬 검증: 실제 PostgreSQL 17 테스트 전용 컨테이너(55432)에서 pytest 105 passed, ruff check/format(CI 범위 `backend tests migrations`) PASS, 프런트 빌드 PASS, Playwright 9/9 개별 실행 3회 PASS. CI [38920566640](https://github.com/InryeolChoi/SerenTable/actions/runs/38920566640) `916d376` **SUCCESS**(3m24s, PR #28 head). **로컬 실행 주의:** pytest는 `PYTHONPATH=backend`와 `TEST_DATABASE_URL`(`postgresql://serentable:localtest@127.0.0.1:55432/serentable_test`)이 필요하고 conftest가 alembic·시드를 하위 프로세스로 실행한다. 배포 환경 브라우저 E2E는 데모 계정 자격 증명이 이 세션에 없어 미완료.
- **PR #27 CI 실패 해소(2026-10-16, OpenRouter DeepSeek 세션, Claude Code 도구):** 통합 브랜치 `codex/apply-matching-integration` HEAD `f24ba46`, Draft PR [#27](https://github.com/InryeolChoi/SerenTable/pull/27) → main (Refs #4 #5). CI [38915264719](https://github.com/InryeolChoi/SerenTable/actions/runs/38915264719) **SUCCESS**. 원인은 `frontend/e2e/events.spec.ts:45`의 페이지 전역 `getByRole("status")`가 회차 생성 성공 알림과 목록 재조회 로딩 안내(`회차를 확인하고 있습니다…`)를 동시에 잡아 strict mode 위반이 난 것이다. 목록 GET 응답만 지연시키는 임시 진단 스펙으로 `role="status"` 2개 동시 존재와 수정 전 단언의 `strict mode violation` 실패를 재현해 확인했다(진단 파일은 실행 후 삭제, 커밋하지 않음). 수정은 **테스트 1곳만** 변경(단언 locator를 `filter({ hasText: "을지로 회차를 만들었습니다" })`로 좁힘). 제품 화면·API·정책·마이그레이션 변경 없음. 로컬 검증: 실제 PostgreSQL 17 테스트 전용 컨테이너 `serentable-foundation-pg`(55432, 실행 지침 문서 기준)에서 pytest 105, ruff check/format PASS, 프런트 빌드 PASS, Playwright 9/9 개별 실행 3회 연속 PASS. `--repeat-each`는 webServer의 DB 초기화가 실행당 1회라 상태 의존 스펙(payments)에서 거짓 실패가 나므로 쓰지 않는다. 참고: 이 세션은 55437 통합 PG18 컨테이너의 접속 정보가 없어 55432 문서 기준 컨테이너로 검증했고, 그 컨테이너는 중지 상태에서 시작해 사용했다. 배포 환경·실기기 검증은 여전히 미완료.
- **중단 지점(2026-10-16 약 23:05 KST, Claude Code, 사용량 한도로 중단):**
  - Git: 통합 브랜치 `codex/apply-matching-integration` HEAD `f24ba46` push 완료(이후 사용자 머지로 main에 포함, 2026-10-17 현재 `codex/work4-task3-notice-assertions` 작업 중), 미커밋 제품 변경 없음(사용자 변경 `AGENTS.md` 수정, 미추적 `.claude/`·`.codex/`·`scripts/claude-deepseek.sh`·`scripts/claude-glm.sh`는 커밋하지 않음). PR [#27](https://github.com/InryeolChoi/SerenTable/pull/27) → main (Refs #4 #5) **병합 완료**. PR #26은 #27에 포함되어 닫음. PR [#28](https://github.com/InryeolChoi/SerenTable/pull/28)은 Task ③ 테스트 전용 변경으로 열려 있다. 로컬 브랜치: main, codex/apply-matching-integration, codex/work4-task3-notice-assertions, codex/work4-rounds-regions, codex/core-design-integration(병합 완료, 원격도 정리 가능). 하위 에이전트 작업 트리는 모두 정리함.
  - 완료: Work #3 종료(Issue #3). Work #4 ①-a·①-b·①-c·② 구현과 Work #5 필수조건 검증기를 통합 브랜치에 병합. 로컬 PostgreSQL 18(55437)에서 pytest 105, Playwright 9/9 연속 2회 PASS.
  - **PR #27 CI 실패는 해소됨(맨 위 항목).** 실패 run은 `npm run test:e2e`의 `events.spec`(운영자 회차 생성→참가자 조회) `getByRole('status') resolved to 2 elements`(strict mode)였고, 원인은 회차 생성 뒤 목록 재조회 로딩 안내가 같은 `role="status"`로 동시에 렌더링되는 것이었다. 수정 전 이력은 [38912016784](https://github.com/InryeolChoi/SerenTable/actions/runs/38912016784).
  - 다음 작업: ① ~~PR #27 Draft→Ready 전환~~ → 사용자 머지 완료(2026-10-16). Railway 배포 후 신청·결제 흐름 배포 검증은 남음 ② CEO 답변 반영(U03 3항목 + 멤버십 중복 구매·적용 범위) ③ Issue #4 체크박스·Blaybus 기록 갱신(문구는 [구현 기록](../design/implementation-progress.md)의 Work #4 절 참고, 아직 안 함) ④ Work #5 나머지(U05~U09·U17 정책 결정, 시드) 및 매칭 실행기의 회차 `FOR UPDATE` 선행 조건 ⑤ ~~같은 `role="status"` 중복 패턴 정리~~ → PR #28로 진행 중.
- **Work #4 구현 완료·Work #5 검증기 추가(2026-10-16, Claude Code, 사용자 승인으로 하위 에이전트 병렬 구현):** 통합 브랜치 `codex/apply-matching-integration`. ①-a 회차·지역, ①-b 일정 신청, ①-c 이용권·모의결제(U03 임시 규칙 `provisional-2026-10-16`), ② 실패·중복 시험(`tests/test_failure_and_duplicates.py`), 매칭 대상 판정 `backend/serentable/eligibility.py`(결제 여부는 회차 마감 시점 기준), Work #5 필수조건 독립 검증기 `tests/oracle`. 독립 검토(specialist)·통합 Standards/Spec 리뷰 지적을 모두 수정. 통합 DB(55437)에서 pytest 105, Playwright 9/9(2회 연속) PASS. E2E는 이제 실행 전 localhost DB 스키마를 재생성한다(`frontend/e2e/reset-database.mjs`). **CEO 확인 대기:** U03 세 항목 + 멤버십 중복 구매·적용 범위 규칙(payment-contract.md '임시'). **매칭 실행기 선행 조건:** 회차 행 `FOR UPDATE` + DB 시각(application-contract.md). 배포 환경·실기기 미검증.
- **Work #4 Task ①-a 모집 회차·지역 설정 구현(2026-10-16, Claude Code):** 브랜치 `codex/work4-rounds-regions`. 서울 4개 지역 고정 + 회차 생성/조회 API·화면([계약](../design/event-slot-contract.md)), 마이그레이션 `0004_event_slot`(되돌리기/재적용 확인). pytest 40, Playwright 7/7 PASS(로컬 PostgreSQL 18). 회차 수정·취소는 ①-b 이후. Work #3은 사용자 확인으로 Issue #3 종료. 로컬 브랜치 정리: main에 병합된 브랜치·깨끗한 Codex 작업 트리 8개와 `ci-gate-probe`(실험, 결과는 ci-gate-verification.md) 삭제. 미커밋 변경이 있는 분리 HEAD 작업 트리 `.codex/worktrees/9846`, `a025`는 보존.
- **Work #3 배포 인증 검증 완료(2026-10-16, Claude Code):** 사용자가 Railway production API 서비스에 `APP_ENV`·`APP_ORIGIN`·`AUTH_SIGNING_KEY`·`DEMO_PARTICIPANT_PASSWORD`·`DEMO_OPERATOR_PASSWORD`를 설정하고(값은 저장소·대화에 없음) PR #25를 main에 머지했다(`a385ac6`, CI 38900300995 PASS, Railway SerenTable·worker Online). `railway ssh`로 컨테이너 안에서 `seed_demo_accounts`를 실행했다(`synthetic_demo_accounts_ready`). 공개 URL에서 HTTP→HTTPS 301, `__Host-` Secure/HttpOnly/SameSite=Lax 쿠키, no-store, 익명 401, 외부 출처 403, 오답 401, readiness/worker 200을 확인했고, 사용자가 별도 터미널에서 `scripts/verify_deployed_auth.py`를 실행해 13/13 PASS(로그인·세션·admin 403·본인 프로필·로그아웃). 운영자 계정의 배포 로그인, 배포 환경 브라우저 E2E, 실제 모바일 기기는 미검증. Claude Code 세션의 Railway 허용 명령은 `.claude/settings.local.json`의 link/status/logs/ssh뿐이다.
- **2026-10-16 11:42Z 사용자 머지:** PR #13(`c5c3f4e`)·#23(`0dbd563`)이 `main`에 머지됐다(PR #22는 `eae10de`로 공통 브랜치 경유). 아래 표·기록의 "PR #13/#23 열림" 서술은 이 시점 이전 상태다. Issue #17·Work #15 종료 여부는 GitHub에서 확인한다. 통합 브랜치에 `main`을 병합(내용 변경 없음)해 PR #25 충돌 표시를 해소했고 CI 38896894745 SUCCESS.
- 저장소: https://github.com/InryeolChoi/SerenTable . 루트 통합 브랜치 `codex/core-design-integration`, 최신 HEAD는 실제 Git에서 확인한다. Draft PR [#25](https://github.com/InryeolChoi/SerenTable/pull/25)에 통합 결과를 전달한다. main 배포와 통합 브랜치를 구분한다.
- 사용자 승인으로 ERD 뷰어를 `docs/design/erd/erd.html`로 정식 변경했다. 승인된 이름 변경 커밋 `9ef90d0`이며 미확인 사용자 변경으로 남아 있지 않다.
- Work #2 후속 PR #24의 공통 브랜치 머지를 확인했다(merge `3869396`, 2026-10-16T10:44:14Z). 비용·백업·원격 검증 인수 완료. 공통 PR #13은 아직 main에 미머지다.
- Work #15 ERD·UI 브랜드 보완은 통합 `9e3a1b1`에 반영했다. 고정 범위 `750bbb0...9e3a1b1` 독립 Standards/Spec 지적 각각 0건. PR #22/#23 개별 head에 결과를 동기화했고 CI 38889918153/38889907017 PASS. 제품 기능 시험과 구분한다.
- 현재 실행: **참가 신청·이용권·결제 → 로그인·프로필·동의(Work #3)**. 사용자는 사전 발급 합성 계정만 제공, Instagram 필수 수집·타 참가자 비공개를 승인했다. [ADR-0008](../adr/0008-demo-accounts-and-private-profile.md)과 [API 계약](../design/account-profile-contract.md)을 따른다. 공개 가입·실제 개인정보 모집·미확정 보관 날짜는 추가하지 않는다.
- **Work #3 세 구현 브랜치를 통합 브랜치에 모두 병합했다(2026-10-16, Claude Code 인수).** 인증 서버 `1061a09`, 프로필/동의 서버 `d97fb43`, 계정 화면 `codex/work3-account-ui`(Codex 미커밋 E2E를 검토·커밋한 `2e5bc2d` 포함). 화면 커밋에서 운영자 상세 버튼의 접근 가능한 이름이 Chromium에서 `상세 보기 : id`로 계산되던 문제를 명시적 `aria-label`로 고쳤다. 미저장 입력은 React 메모리 상태로만 유지하며 브라우저 저장소를 쓰지 않는다.
- 통합 결과 로컬 검증(실제 PostgreSQL 18 테스트 전용 컨테이너 `serentable-work3-integration-pg18`, 포트 55437): `uv run pytest -q` 30 passed, ruff check/format PASS, 프런트 빌드 PASS, Playwright 4/4 PASS(모바일 Chromium 에뮬레이션: 로그인·권한 거절·로그아웃, 미완성/완성 프로필·목적별 동의 저장·새로고침 유지, 연결 실패·입력 오류·세션 철회 후 같은 계정 미저장 입력 유지와 타 계정 격리, 운영자 상세 360/390/1440px 잘림 없음). 실제 모바일 기기·배포 환경 검증, 독립 Standards/Spec 검토, CI는 아직 아니다. 통합 브랜치 push 여부는 GitHub에서 확인한다.
- 구현 트리: `core-security/SerenTable`의 `codex/work3-auth-server`, `core-ui/SerenTable`의 `codex/work3-account-ui`, `foundation-safety/SerenTable`의 `codex/work3-profile-consent`. 공통 부모 경로는 `/Users/inchoi/.codex/worktrees/`다. 세 브랜치 모두 통합에 반영되어 미커밋 변경이 없다.

## Codex 인계: Work #6 Task ①-b 독립 검증 안내 (2026-10-17 01:20 KST)

검증 기준을 고정한다: 구현 `d15cd78`, 기록 `3dbb46f`(둘 다 PR #31 head 가계), 기준 `origin/main` `6d707cb`. 계약 문서(`docs/design/matching-contract.md`)는 **PR #30 브랜치 `codex/work6-matching-contract`(`4e40fa2`)에만 있으므로** 계약 대조 시 그 브랜치를 함께 확인한다.

검증 명령(로컬 테스트 전용 컨테이너 `serentable-foundation-pg`, 127.0.0.1:55432). 컨테이너 생성·시작과 환경 변수(`DATABASE_URL`·`TEST_DATABASE_URL`·`PYTHONPATH`)는 [운영 지침](../operations/foundation-runbook.md) 29~83행이 기준이며 같은 명령을 중복 실행하지 않는다:

```bash
uv sync --locked
uv run alembic upgrade head
uv run pytest -q                                  # 기대: 115 passed
uv run ruff check backend tests migrations        # 기대: All checks passed
uv run ruff format --check backend tests migrations
npm run build --prefix frontend                   # tsc --noEmit + vite build
npm run test:e2e --prefix frontend                # 기대: 10 passed (webServer가 스키마 재생성, --repeat-each 금지)
uv run python -m serentable.worker --once         # heartbeat 1회 + 마감 회차 매칭 1회
```

독립 검증 관점(구현을 다시 쓰지 않고 계약·불변조건을 확인):

- **계약 대조:** 승인 항목(하드 제약·U06 배정·U07 소유권·MAT-01) ↔ `backend/serentable/matching.py`, `migrations/versions/0007_matching.py`. **알려진 의도적 차이 1건**: 계약 76행 `UNIQUE(application_id)` ↔ 구현은 `WHERE ended_at IS NULL` 부분 유니크 인덱스(①-c 재배치가 이력을 남겨야 함). PR #30 머지 후 계약 문장을 정정한다.
- **정답 대조:** `tests/test_matching_runner.py`의 오라클 대조 시험이 같은 입력에서 `seated_count`와 `max_seatable()`을 비교하고 `validate_assignment()` 위반 0을 확인한다. 실행기 코드는 `tests/oracle`을 import하지 않는다(독립성 확인).
- **MAT-01:** `matching.py`의 라우터에는 읽기 전용 `GET /api/admin/match-runs`만 있고 매칭 시작·확정·수정 엔드포인트가 없다. 실행 경로는 `worker.py`의 `match_due_slots()` 하나다(`app.include_router(matching_router)`는 조회용).
- **U06:** 제출 순서가 tie-break다. 같은 나이 입력에서 제출 순서를 뒤집으면 남는 집합이 달라져야 한다.
- **U07:** 한 신청의 살아 있는 배치 하나(부분 유니크), `matches_at` 오름차순 처리, 이미 `CONFIRMED`인 신청 제외 — 동시 실행·중단 재개·복수 회차 시험으로 확인한다.
- **알려진 한계(결함 아님, 계약에 명시):** 12명 초과 회차는 결정적 그리디로 내려가 배정 인원 최적성을 주장하지 않는다(`MAX_EXHAUSTIVE_PARTICIPANTS`, 실행 규모 U19 미확정). 점수·성별 비율·MBTI는 쓰지 않는다(U05 미확정). 확정은 ①-b에서 최종이며 취소·재배치(U13)는 미결정이라 뒤 실행이 덮어쓰지 않는다.
- **미검증:** 배포 환경 실행기 동작과 브라우저 E2E(데모 자격 증명 없음), 실제 기기, 실행당 100명 규모 성능, Railway 마이그레이션 0007 적용.

주의: 별도 브랜치/작업 트리에서 검증하고 같은 checkout을 동시에 수정하지 않는다. 미커밋 사용자 변경(`AGENTS.md` 수정, 미추적 `.claude/`·`.codex/`·`scripts/claude-deepseek.sh`·`scripts/claude-glm.sh`)을 복원·삭제·stage하지 않는다.

## 최신 주최 측 안내: 2026-10-16

현재 기록 작업은 **개발·배포 기반 확보 → 요구사항·설계·자료 정리 → 기술 결정 및 미결정 항목 정리 / PRD·구글폼·킥오프 차이 기록**의 보강이다. 사용자가 전달한 [공식 안내·FAQ](../design/official-faq-2026-10-16.md)를 다음 제품 작업 전에 읽는다.

- 1회권 9,900원, 멤버십 1/3/6개월 35,000/75,000/120,000원. 기간 내 참여 횟수 무제한, 매칭 실패 횟수만큼 기한 연장. 연장 단위·기산점 등은 U03 미정.
- 현행 환불 제한은 화요일 24:00 이후. 매칭 마감과 같게 둘지는 재량이며 시스템 실패 환불 예외 등 U04는 남음.
- 서울 4개 지역 운영, 운영자 사전 검토 없는 자동 확정. Hard 조건 완화 금지. 성비·MBTI·취소/노쇼 세부 정책은 PRD 범위 내 개발자 재량.
- 문의/운영 로그와 로고 원본 미제공, 로고 재현 허용. 원본 수령을 개발 선행 조건으로 두지 않음.
- Workspace 목표에는 10/15~10/21과 결과물을 기재. 같은 Task에서 타이머 재사용, 종료 후 별도 완료 버튼. 제출탭에 10/21 23:59까지 배포 링크·테스트 계정 제출.
- FAQ 전 항목 대조, 명세 U03/U04·출처 대조·ADR-0007의 미정 설명 보완, 문서 링크/차이 검사로 검증한다. 제품 기능·DB·배포 변경과 정책 추가 결정은 없다.

## 제품 목표와 확정 방향

- 2026-10-21 23:59 제출, 실질 개발 완료 목표 10/20. PRD P0·12단계 E2E를 심사용 배포에서 증명한다.
- React·TypeScript·Vite CSR을 FastAPI가 제공한다. 같은 Python 코드베이스의 API/별도 worker, PostgreSQL을 Railway 한 프로젝트에서 실행한다.
- 정상 신청→모의 결제→자동 매칭/확정→가상 식당/단체방/안내→피드백을 운영자 승인 없이 연결한다. 예외만 운영자에게 전달한다.
- 신뢰성(멱등·동시성·재시도·복구)을 주력으로 검증하고 매칭의 필수조건·작은 입력 독립 정답 비교를 확보한다. 실행당 100명은 검증 목표이며 현재 성능 보장이 아니다.
- 현재 적용한 업무 외 DB 테이블은 `worker_heartbeat`뿐이다. 로그인·프로필·신청·결제·매칭 등 업무 기능과 가상데이터 적재는 아직 구현하지 않았다.
- 상세 기준·U01~U20은 [구현 명세](../design/mvp-implementation-spec.md)를 따른다. 결제는 1회권+모의 구독이며 실제 폼의 3회권과 동일시하지 않는다.

## 현재 Agenda·Work·Task와 PR

공통 Agenda: **개발·배포 기반 확보**. 아래 머지 상태는 2026-10-16 GitHub 조회 결과이며 바뀌면 갱신한다.

| Work → Task | Issue / PR | 확인한 결과·남은 일 |
|---|---|---|
| 첫 배포·CI·DB 연결 → 배포 안전장치·원격 작업 검증 | #16 / PR #20 | 사용자 머지 완료, 단 `codex/sync-foundation-tasks`에 머지됨. 원격·CI·readiness 검증 완료. Compute $10/$20 한도 설정 완료. 실제 Railway 백업·격리 복원 완료. 후속 PR #24 검토·머지 대기 |
| 핵심 데이터·화면·보안 설계 → 핵심 ERD·상태·무결성 제약 설계 | #17 / PR #23 | 열린 PR. 문서·SVG/PNG 각3장·확대 뷰어와 생성 스크립트 제공. 최신 그림은 설계안이며 실제 DB 적용 아님 |
| 같은 Work → 공통 UI·핵심 화면 흐름 설계 | #18 / PR #22 | **완료.** 사용자 머지 `eae10de`(2026-10-16T11:40:06Z, base `codex/sync-foundation-tasks`), Issue #18 수동 종료. 브랜드 보완(갈색·크림색·원형 식탁) 반영, CI 38889918153 PASS, 독립 Standards/Spec 0건. 최종 시각 승인·실제 기기 시험은 후속 기능 Work |
| 같은 Work → 개인정보·권한·보안 검증 기준 정리 | #19 / PR #21 | 사용자 머지 완료, 위 공통 브랜치에 포함. 검증 기준 설계 완료이며 실제 제품 보안 시험과 구분 |

PR #13(`codex/sync-foundation-tasks` → main)은 아직 열려 있다. PR #20/#21 머지를 main 배포로 해석하지 않는다. 부모 Work #2/#15나 Agenda 전체를 완료 처리하지 않았다. [상세 결과·Blaybus 복사 문구](../design/parallel-task-results.md)를 확인한다.

## 검증 증거와 운영의 미완료

- 운영 골격은 PR #12로 main에 배포했다. 공개 URL: https://chanceplate.up.railway.app . 마지막 확인 버전 `cef5df1`(PR #14 병합), health/readiness/worker-health 200과 세 서비스 SUCCESS/replica 각1을 확인했다. 현재 상태는 다시 조회한다.
- CI 실패 배포 차단은 실제 실패→SKIPPED/복구→SUCCESS 실험을 수행했다. API·worker main/checkSuites=true, worker Start `python -m serentable.worker`, Pre-deploy 빈 값. API Pre-deploy Alembic, healthcheck `/api/readiness` 300초. [증거](../operations/ci-gate-verification.md).
- 사용자 휴대폰 접속 보고와 `REMOTE-20261016` 지시 → commit `73c056b` → PR #20 → CI `38760875571` success를 확인했다. 기종/OS 직접 검증으로 확장하지 않는다.
- 사용자 화면: Hobby 사용량 $0·포함 $5·Agent 한도 $5. Compute 한도는 별개이며 미확인. Postgres No Backups·새/예약 백업과 PITR의 Pro 기능 제한 확인. 유료 플랜 변경은 하지 않았다. 실제 Railway 데이터 논리 백업·복원 준비가 남아 있다.
- 로컬 별도 DB의 백업/복원은 이전에 통과했으나 클라우드 데이터 복구 검증을 대신하지 않는다. [운영 최신 기록](../operations/deployment-safety-verification.md).
- ERD 원문 3개 Mermaid 렌더링, PNG 육안 확인, 뷰어 그림 전환·200% 확대·맞춤 확인. UI 독립 스케치 360/1440px 브라우저 검토. 실제 제품 기능 E2E는 아님.
- 공통 기록 갱신 보강: AGENTS.md에서 작업 결과·검증·중단·전환 때 기록 갱신을 의무화하고 Claude/Gemini/Copilot 진입 파일을 구성했다. 진입 파일 참조·문서 상대 링크·git diff --check를 확인했다. ERD 기준 문서는 아직 공통 PR 브랜치에 없으며 Task PR/통합 브랜치에서 존재를 확인했다. 각 도구의 실제 세션 자동 로딩과 외부 인증 공유는 검증하지 않았다.
- 최근 변경 CI: PR #22 `38765386668`, PR #23 `38765765265` verify SUCCESS. 이후 커밋이 있으면 최신 head의 CI를 확인한다.
- 초기 네 Task 고정 범위 `4f41619...6357379` 독립 Standards/Spec 각각 0건. 후속 시각화/브랜드 대조는 그 리뷰 범위와 구분한다.

## 2026-10-16 재개 확인

- 루트 HEAD `b6de489`, 통합 브랜치와 origin 일치. 기존 ERD index.html 삭제/erd.html 미추적 변경 유지.
- GitHub 조회: PR #13/#22/#23은 열림. Task #16~#19와 부모 Work #2/#15도 열림. 보안 PR 머지와 Issue 완료 상태는 별개다.
- 공개 `/api/readiness`는 ready/database connected, `/api/worker-health`는 alive를 재확인했다. 제품 업무 E2E나 전체 Railway 리소스 조회를 대신하지 않는다.
- 문서 PR #13 최신 조회 CI [38857500407](https://github.com/InryeolChoi/SerenTable/actions/runs/38857500407) verify PASS.
- 이 재개 점검은 Task 완료가 아니다. Blaybus에서는 기존 Task #16 타이머를 재사용하고, 비용 한도·실제 백업/복원 미완료를 유지한다.

## Task #16 후속 진행: 비용·백업 경로

- 작업 브랜치 `codex/task16-backup-restore`, 기반 `codex/sync-foundation-tasks`. 기존 Task #16의 후속 PR로 진행하며 새 Work/Task는 만들지 않았다.
- 사용자 승인으로 Compute $10 알림·$20 중단 한도를 CLI로 실제 설정·재조회했다. 조회 시 약 $0.05227 사용량, 한도 미도달. Agent $5 한도 유지.
- Railway 실제 DB 이미지가 PostgreSQL 18임을 확인했다. 백업·복원은 18 도구로 검증하며 기존 로컬/CI 17을 같은 환경으로 표시하지 않는다.
- `scripts/postgres_recovery.py`, `scripts/verify_postgres_recovery.py`, 운영 지침과 CI 검증 추가. 실제 로컬 PostgreSQL 18의 독립 원본→백업→새 DB 복원→HTTP readiness·worker 검증 통과. 기존 파일·원본 보존, 손상/공개 경로 거부도 통과.
- CLI 로그인·전용 클라이언트 공개키 등록 완료. SSH 최초 신뢰 등록은 자동 승인 검토에서 독립 검증 부재로 거절된 후, 사용자가 정확한 서버 지문과 위험을 확인해 명시 승인했다. 동일 프롬프트에서 승인한 지문만 등록하고 실제 SSH 백업을 수행했다. 개인키는 호스트 SSH 디렉터리에서만 보관한다.
- **실제 Railway 데이터 백업·격리 복원과 코드 CI 검증 완료.** 로컬 전용 `.local-backups/railway-20261016-recovery-01.dump` (2,707바이트·0600, 원본/pg_dump 18.6)를 새 PostgreSQL 18에 복원하고 heartbeat 1행·API readiness·worker-health를 확인했다. 운영 DB에는 복원하지 않았다. 수동 사본이며 자동 백업/별도 장기 보관소·업무 데이터 복원 검증은 구성하지 않았다.
- 초기화 임시 서버를 준비 완료로 오인한 CI 실패를 지연 fixture로 재현해 TCP 검사로 수정했다. 회귀 검사 및 코드 커밋 `5508d58`의 CI 38887784923 PASS. 후속 [PR #24](https://github.com/InryeolChoi/SerenTable/pull/24) 검토·머지 전 Task #16/Work #2 Issue는 열린 상태를 유지한다. 최신 문서 커밋 CI는 PR Checks에서 재확인한다.
- 사용자 ERD 파일명 변경은 보존했다. 루트의 직전 재개 점검용 HANDOFF 변경은 이 기록에도 포함했다.

## 다음 작업 순서

1. 현재 Git/PR과 활성 구현 작업 트리를 확인한다. 위 최신 상태가 아래 과거 진행 기록보다 우선한다.
2. Work #3 통합·CI(38895117676 PASS)와 고정 범위 `9e3a1b1...8519f12` 독립 검토를 완료했다. Standards 확정 위반 0건(판단 사항: 테스트의 DB 직접 상태 준비, auth.py import 순서, 503 처리 중복, main.tsx 단일 파일 등은 마감 후 리팩터링 후보). Spec 지적 중 기능 결함 4건을 `codex/work3-review-fixes`(`73308e9`)에서 수정했다: CSRF 만료 시 새 토큰으로 1회 재시도, 인증·CSRF를 본문 검증 전에 판정(로그인 포함), 이전 스키마 프로필 행을 행 단위 `unreadable`로 보고, `KeyError`의 503 변환 제거(`DATABASE_URL` 누락은 전용 SQLAlchemy 예외). 각 수정의 회귀 시험이 수정 전 코드에서 실패함을 확인했다. pytest 32, Playwright 5/5 PASS.
   - **사용자 결정 3건 반영(2026-10-16, ADR-0008 추가 결정):** 동의 이력은 서버 보존으로 충족(열람 API 없음), 해시 동시 처리 한도 초과는 503 `login_busy`+`Retry-After: 1`로 계정 잠금 429와 구분, `/api/me/profile`·`/api/me/consents`는 참가자 전용(운영자 403 `participant_required`). 브랜치 `codex/work3-policy-decisions`, 회귀 시험이 수정 전 코드에서 실패함을 확인. pytest 34, Playwright 6/6 PASS.
   - Blaybus 위치 정정: Work #3은 Agenda **참가 신청·이용권·결제** 소속이다(개발·배포 기반 확보 아님). Task는 ① 수집 필드·권한·화면 구현, ② 필수값·접근 권한 검증. 검토·수정은 ②, 정책 결정 반영은 ①에 기록한다.
3. Railway 프록시 HTTPS 판정은 방안 A(`X-Forwarded-Proto` 직접 확인)로 해소했다. Issue #4 Task ①은 ①-a 회차·지역 설정/①-b 일정 신청/①-c 이용권·모의 결제(U03·U04 선행)로 분할했다(사용자 승인).
4. 이후 Work #4는 U03/U04 등 해당 사업 정책 선행을 확인한다. 합성 계정 승인으로 결제·환불·매칭 정책을 확정하지 않는다.

## 설정·접근은 어디에 두는가

| 종류 | 위치·공유 방법 | 현재 확인 |
|---|---|---|
| 공통 작업 규칙 | 루트 AGENTS.md. Claude는 CLAUDE.md, Gemini는 GEMINI.md, Copilot은 .github/copilot-instructions.md에서 참조. Cursor는 루트 AGENTS.md 사용 | 파일·참조를 구성함. 각 도구의 실제 세션 자동 로딩은 미검증이며 첫 세션에서 읽은 지침 확인 |
| 결정·업무 언어 | docs/adr/, GLOSSARY.md, 구현 명세의 U 항목 | 기존 문서를 기준으로 하고 중복 정책 파일을 만들지 않음 |
| 현재 작업·미완료·다음 행동 | 이 HANDOFF.md + GitHub Issue/PR | 기록 갱신 절차에 따라 작업 결과 확정·주요 검증·중단·전환 시 에이전트가 직접 갱신 |
| Codex 설정 | 사용자 ~/.codex/config.toml, 필요 시 프로젝트 .codex/config.toml | 프로젝트 설정 없음. 개인 설정 내용/인증은 복사하지 않음 |
| Claude 설정 | 공유 .claude/settings.json, 개인 .claude/settings.local.json | 둘 다 현재 프로젝트에 없음. 이 요청에서 권한/모델 설정을 새로 부여하지 않음 |
| Claude MCP | 프로젝트 .mcp.json, 사용자 범위 설정·OAuth는 해당 도구에서 관리 | 프로젝트 .mcp.json 없음. Codex의 Railway/앱 연결이 Claude로 이식됐다고 가정하지 않음 |
| GitHub | 같은 호스트의 gh CLI 또는 각 도구의 GitHub 연결 | Codex에서 gh 조회 성공. 다른 호스트에서는 gh auth status로 접근 여부 확인 |
| Railway | Codex 연결 도구, Claude에서는 별도 MCP/CLI 연결 필요 여부 확인 | npm exec 기반 Railway CLI 5.69.0 로그인·비용 한도 조회 확인, Claude 접근 미검증. 설정값·비밀값을 인계 문서에 저장하지 않음 |
| 스킬 | ~/.agents/skills/의 실제 SKILL.md와 도구별 skills 디렉터리 | 공통/Claude 디렉터리 존재. 동일 slash 명령 등록·모든 도구 실행 가능 여부는 미검증 |
| 모바일 원격 | 연결된 Codex 호스트·기기 구성 | 기존 Codex 경로만 사용자 지시로 검증. Claude 모바일 연동을 구성한 것은 아님 |

로컬에서 `claude --version`은 `2.1.300`이었다. 실제 Claude 모델 세션을 실행하거나 로그인·과금·MCP 연결을 변경하지 않았다. 도구별 자동 메모리와 대화 resume는 보조 수단이고 공통 문서·Git 이력을 인계 기준으로 사용한다.

## 모든 에이전트에서 사용할 재개 프롬프트

```text
AGENTS.md와 docs/agents/HANDOFF.md를 읽고 현재 Git 상태와 GitHub PR 상태를 대조해 주세요.
미커밋 사용자 변경은 보존하고 현재 Agenda → Work → Task, 완료/미완료, 바로 할 다음 행동을 짧게 정리해 주세요.
도구 접근이 확인되지 않으면 사용 가능하다고 가정하지 마세요. 새 기능 구현은 제가 지정한 Task 범위에서 진행하세요.
docs/agents/record-maintenance.md에 따라 작업 결과·검증·중단 시 관련 문서와 인계 기록을 별도 요청 없이 갱신하고 Blaybus 기록 문구·실제 PR 링크를 제공해 주세요.
```

기록 갱신 기준은 [공통 기록 갱신 절차](record-maintenance.md)에 모았다. 이번 변경은 기존 Work #1의 기술 결정 및 미결정 항목 정리 결과에 대한 운영 지침 보강이며 새 제품 Task를 만들지 않는다. 커밋/PR 링크를 남기고, 두 도구가 같은 checkout을 동시에 수정하는 상태는 해소한 뒤 넘긴다. 별도 작업 트리에는 공통 미커밋 변경이 자동 복사되지 않는다.

공식 근거: [OpenAI AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Claude 프로젝트 메모리](https://code.claude.com/docs/en/memory), [Claude 설정](https://code.claude.com/docs/en/settings), [Claude MCP](https://code.claude.com/docs/en/mcp). [Gemini 지침·파일 가져오기](https://geminicli.com/docs/cli/gemini-md/), [Cursor AGENTS.md](https://cursor.com/docs/rules), [GitHub Copilot 저장소 지침](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions). 사용자 도구·모델·계정 설정은 해당 세션의 실제 상태를 우선한다.
