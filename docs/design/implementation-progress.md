# MVP 구현 분류 및 실행 기록

**2026-10-17 실제 배포 인수:** PR #31 main `93195f6`의 API/worker 배포와 공개 HTTPS의 합성 로그인→회차→신청→모의 결제 실패/성공→재전송→상태 조회→취소 검증을 완료했다. [실행 증거·잔여·Blaybus 문구](../operations/application-deployment-verification.md)를 기준으로 현재 모의 MVP 범위의 신청·이용권·결제 Agenda 완료를 안내한다. 연장/환불 정책과 배포 브라우저·실기기를 완료한 것은 아니다.

**2026-10-17 후속 검토:** 기존 PR #31에서 인원 최대화·마감 판정·취소/결제·실패 기록·외래키 교착 및 E2E 순서 의존성을 재현·수정하고 확정 테이블 표시명 소개를 연결했다. [검토 기록](implementation-review-2026-10-17.md)에 기준 커밋·환경·결과·Blaybus 문구·미완료를 구분한다. 전체 Work #6 완료나 새 운영 배포로 해석하지 않는다.

기준: 2026-10-15, Asia/Seoul. 사용자가 `implement-spec`으로 현재 구현 가능한 작업의 분류와 실행을 요청했다. 앞선 10/16 시작 계획보다 최신 구현 시작 요청을 우선한다. 기본 순서는 Agenda → Work → Task를 유지한다.

## 작업 위치와 브랜치

- 최초 통합 브랜치: `integration/mvp`. PR #12가 main의 `1407e23`에 병합되었고 현재 Railway 배포 브랜치는 `main`이다.
- 기준 커밋: 원격 main의 `b92b1d6`. 명세 PR #11이 병합된 상태에서 시작했다.
- 현재 Work: 개발·배포 기반 확보 → 첫 배포·CI·DB 연결, GitHub Issue #2.
- 구현자는 별도 작업 트리/브랜치에서 승인된 외부 행동 경계를 대상으로 TDD를 진행한다. 구현 후 통합 브랜치에 병합하고 독립 검증·리뷰를 수행한다.

## 분류

| Work | 상태 | 현재 실행 범위 또는 선행 조건 |
|---|---|---|
| #1 요구사항·설계·자료 정리 | 완료 | PR #11 병합, 세 Task의 문서·승인 검증 경계·자료 검토 확인. Issue 종료 |
| #2 첫 배포·CI·DB 연결 | 등록 5개 Task 인수 완료 | 비용 한도·실제 PG18 백업/격리 복원·원격 검증 완료, 후속 PR #24 공통 브랜치 머지 확인 |
| 공통 설계 핵심 데이터·화면·보안 설계 | 설계 3종 작성·독립 검토 완료, PR 검토 준비 | 사용자 병렬 승인에 따라 배포 검증과 병행. [Task별 결과](./parallel-task-results.md). 후속 제품 정책·물리 스키마는 별도 |
| #3 로그인·프로필·동의 | 구현 중 | 합성 계정·Instagram 필수/비공개 승인. 인증·UI·프로필/동의 별도 트리 병렬 구현, 최종 E2E·보안·배포 미완료 |
| #4 일정 신청·이용권·모의 결제 | 대기 | #3, 모의 구독·환불·취소 정책 U03/U04 필요 |
| #5 규칙·데이터·정답 기준 | 정책 결정 필요 | 정책 검토는 먼저 가능하나 새 DB 시드 Task는 #4 업무 스키마가 필요. 기본 순서도 #4 다음. U05~U09/U14/U17/U19 확정 필요 |
| #6 예약 매칭·재배치·실패 해결 | 진행 중 | ①-a 계약 승인·①-b 자동 실행기 완료(아래 Work #6 절). ①-c 미매칭 대안·이동/보관/환불, U05 점수, 100명 규모(U19) 필요 |
| #7 식당·채팅·알림 | 대기 | #6, 음식/가격 검증·채팅/푸시·재시도 기준과 실제 기기 확인 필요 |
| #8 참석·피드백·다음 추천 | 대기 | #7, 피드백·신고·체크인·공개/보관 정책 필요 |
| #9 운영자 예외·안전 종합 관리 | 대기 | #8. 기본 권한·운영 설정·예외 처리는 이전 기능 Work와 함께 구현 |
| #10 통합 검증·제출 | 대기 | #9 및 배포·기기·데모·정량 수용 기준 검증 |

## 외부 접근과 검증 조건

- 로컬 Docker Desktop을 시작했고 Docker 서버 `29.8.2`를 확인했다. 실제 PostgreSQL을 사용한 통합 테스트를 준비한다.
- 초기 로컬 Railway 로그인은 없었으나 이후 사용자가 서비스를 구성하고 Railway 연결 도구도 연결했다. 공개 배포는 검증했으며 비용·예산 설정은 아직 확인하지 않았다.
- 제품 동작에 영향을 주지 않는 런타임·의존성·검사 도구 선택은 구현자가 근거와 함께 정리한다. 구독·매칭·신고 등 사업 정책을 임의로 확정하지 않는다.
- 실제 사용자 시간은 추정하지 않는다. 테스트 결과와 실행 환경·미완료 조건을 분리해 기록한다.

## Blaybus 수동 갱신 요청

완료한 Work #1: `개발·배포 기반 확보 > 요구사항·설계·자료 정리`의 세 Task에 PR #11을 연결한다. 요구사항 차이·데이터 검토·기술/미정 명세의 결과물을 확인한 뒤 Work를 완료로 바꾸도록 사용자에게 요청했다. 사용자 실제 반영 여부는 아직 확인하지 않았다.

현재 Work #2는 진행 중이다. 완료한 Task별 실제 PR·검증 근거는 아래에 제공한다. 다음 Work를 실행하거나 새 Work/Task를 추가할 필요가 생기면 이유·위치·완료 기준·일정 영향을 먼저 안내한다.

## Work #2 구현과 검증 결과

검토 산출물: [병합된 PR #12](https://github.com/InryeolChoi/SerenTable/pull/12). 제품 기능이나 Work 전체 완료를 뜻하지 않는다. 관련 실행 지침은 [첫 배포 실행 지침](../operations/foundation-runbook.md)이다.

- Python 3.12·Node 22·PostgreSQL 17, uv 잠금 파일, SQLAlchemy/psycopg·Alembic을 기반 도구로 선택했다. U18 중 런타임·DB 도구·자동 검사 구성만 구현했고 외부 운영 설정은 남아 있다.
- React CSR의 홈·참가자·운영자 준비 화면을 FastAPI 이미지에 포함한다. 로그인·관리자 권한·업무 데이터는 아직 없다.
- liveness, PostgreSQL 실제 query 기반 readiness, 별도 실행기의 heartbeat 관측 API를 제공한다. worker는 연결 확인용이며 예약 매칭·알림 엔진을 구현한 상태가 아니다.
- 실제 PostgreSQL HTTP 통합 **7개**, 모바일 크기 Chromium **1개**, Ruff 검사, Node22/Python3.12 Docker 빌드가 통과했다. TDD에서 API/화면 미구현 404와 worker 모듈 부재 실패를 확인한 뒤 구현했다.
- Compose의 앱·DB·worker 실행과 readiness/worker-health 200을 확인했다. 별도 브라우저에서도 참가자 경로 이동·새로고침을 확인했다.
- 커밋 `1029210`의 [GitHub push CI](https://github.com/InryeolChoi/SerenTable/actions/runs/38740355994)가 실제 통과했다. PR·`main`·`integration/mvp` push에서 DB 마이그레이션·HTTP·화면·이미지 검사를 수행한다.
- 로컬 DB를 `pg_dump`로 백업하고 별도 빈 `serentable_restore_work2` DB에 복원했다. 복원 DB의 API readiness 200과 별도 worker 실행 후 worker-health 200을 확인했다. Railway 백업 설정·복원 검증과는 별개다.
- 독립 Standards 리뷰는 지적 0건이었다. Spec 리뷰에서는 로컬 테스트 DB 설정 명령 누락 1건을 발견하여 실행 지침을 보완했다. 보완한 환경변수·마이그레이션·테스트 명령으로 HTTP 7개 통과를 다시 확인했다.
- 초기 Railway 미연결 상태는 해소되었다. 실제 API·DB·worker 배포와 사용자 모바일 확인 결과를 아래 최신 상태에 반영한다.

### Blaybus에 반영할 Task 기록

아래 Task의 공통 위치는 `개발·배포 기반 확보 > 첫 배포·CI·DB 연결`이다. 사용자가 각 Task의 작업 내용 기록란에 아래 문구를 넣고 완료 상태로 바꾸도록 요청한다. 실제 투입 시간은 사용자가 기록한다.

**Task: 최소 React·FastAPI 앱 구성 — 완료**

```text
수행: React·TypeScript·Vite CSR의 홈/참가자/운영자 준비 화면을 FastAPI에서 제공하도록 구성했습니다. 같은 Docker 이미지에 화면 빌드 결과를 포함했습니다.
검증: HTTP 경로·미등록 API/정적 파일 404, 모바일 크기 Chromium 이동·새로고침 1개, Node22 화면 타입 검사/빌드 및 Docker 빌드가 통과했습니다. 인증/신청/관리자 권한 기능은 후속 Work입니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/12
```

**Task: DB 연결과 CI 구성 — 완료**

```text
수행: PostgreSQL·SQLAlchemy·Alembic, DB readiness, 별도 heartbeat 실행기, PR/배포 브랜치 CI를 구성했습니다. 연결 실패 응답과 실행기 로그에서 비밀값을 감췄습니다.
검증: 실제 PostgreSQL HTTP 통합 7개, Ruff, Docker Compose 실행 및 GitHub CI가 통과했습니다. 로컬 백업을 별도 DB에 복원한 뒤 API/실행기 연결을 확인했습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/12
```

**Task: Railway 배포 — 완료**

```text
수행: main의 React CSR·FastAPI·PostgreSQL·별도 worker를 Railway에 배포했습니다. worker 상시 명령이 Pre-deploy에 들어간 오류를 수정하여 Start Command로 옮겼습니다.
검증: 공개 /api/health의 main 버전 1407e23, DB readiness 200, worker 최신 배포 SUCCESS·실행 replica 1개·로그 heartbeat 및 worker-health 200을 확인했습니다. heartbeat만으로 배포 완료를 판단하지 않습니다.
배포: https://chanceplate.up.railway.app
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/12 (병합 완료)
```

**Task: 첫 화면 모바일 검증 — 완료**

```text
수행/검증: 사용자가 휴대전화에서 참가자·운영자 화면 이동 시 주소와 제목 변경을 확인했습니다. 사용자가 제공한 23:26 Blaybus 화면에서 이 Task를 완료로 표시한 것을 확인했습니다. 제품 로그인/업무 기능 완료와 구분합니다. 기기 모델·OS·브라우저나 개별 새로고침 결과를 추정하지 않습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/12
```

**Task: 배포 안전장치·원격 작업 검증 — 진행 중**

사용자가 추천 후 추가를 완료했다고 확인했다. 새 기능 범위가 아니라 기존 Work 인수 조건의 남은 검증을 분리한 Task다.

| 순서 | 완료 기준 | 현재 증거/상태 |
|---|---|---|
| 1 | API·worker Wait for CI 활성화 및 실패한 CI의 배포 차단 확인 | 완료: 두 서비스 source.checkSuites=true. 실패 CI의 두 배포 SKIPPED, 정상 복구 CI의 두 배포 SUCCESS 및 main 복구 확인. [실제 검증 기록](../operations/ci-gate-verification.md) |
| 2 | 비용 알림/상한과 Railway 백업·복원 준비 확인 | Hobby 사용량 $0 화면·백업 부재/Pro 제약 확인. Compute 한도·Railway 실제 데이터의 대체 백업 경로 미완료. 로컬 별도 DB 복원은 통과 |
| 3 | 모바일 Codex 지시→GitHub PR→CI 실제 수행 | 사용자 `REMOTE-20261016` 지시 → commit 73c056b → PR #20 → CI 38760875571 success. 기종/OS 직접 확인은 아님 |

외부 설정·기기 접근에 따라 30~60분을 예상하며 실제 투입 시간은 사용자가 기록한다. 2026-10-16 사용자의 네 Task별 독립 Issue 요청에 따라 부모 #2 아래 Task #16을 연결했다. 종합 인수 조건까지 충족한 뒤 Work와 Agenda 완료 여부를 판단하고, 다음 Agenda의 로그인·프로필·동의 Work로 진행한다.

## 사용자 Task 구조 변경 반영

2026-10-15 23:26 화면 기준 네 Task 완료와 뒤이은 추가 완료 답변을 반영했다. 등록 순서는 최신 Blaybus 화면 표시를 따른다.

1. 첫 화면 모바일 검증 — 완료
2. Railway 배포 — 완료
3. DB 연결과 CI 구성 — 완료
4. 최소 React·FastAPI 앱 구성 — 완료
5. 배포 안전장치·원격 작업 검증 — 진행 중

Work `첫 배포·CI·DB 연결`은 진행 중이다. 이 변경은 기존 ‘Railway 배포 및 모바일 검증’ 통합 Task를 대체한다. 사용자 원본 data/는 수정하거나 Git에 추가하지 않는다.


## 2026-10-16 사용자 등록 확인

사용자가 공통 설계 Work 1개·Task 3개 및 기존 데이터 Work의 DB 시드 Task 1개를 Blaybus에 추가했다고 확인했다. [설계 배치](./design-readiness-plan.md)에 확정 상태로 반영했다. 기존 Work Issue와 로그인/데이터 Work의 선행 관계를 유지했다. 이후 사용자 요청으로 네 Task #16~#19를 각각 별도 Issue·PR로 병렬 실행했다. 최신 산출물·검증·Blaybus 문구는 [병렬 Task 결과](./parallel-task-results.md)에 기록한다. 실제 업무 DB 적재는 시작하지 않았다.

## 2026-10-16 최신 구현 경계

Work #2 PR #24는 공통 브랜치에 머지됐다. Work #15 ERD·브랜드 보완과 고정 범위 독립 검토를 마쳤으며 PR #22/#23 최신 CI가 통과했다. 현재 실제 상태는 [인계 기록](../agents/HANDOFF.md) 상단과 [Work #3 계약](account-profile-contract.md)을 따른다. 아래 과거 기록의 비용·브랜드 미완료는 당시 스냅샷이다. 로그인·프로필·동의는 현재 구현 중이며 인증 첫 수직 검증을 전체 기능 완료로 보지 않는다.

## Work #4 구현과 검증 결과

Work #4 `일정 신청·이용권·모의 결제`(Agenda `참가 신청·이용권·결제`, GitHub Issue [#4](https://github.com/InryeolChoi/SerenTable/issues/4))의 구현 결과다. 통합 브랜치 `codex/apply-matching-integration`의 작업이 PR [#27](https://github.com/InryeolChoi/SerenTable/pull/27)로 main에 **병합**되었고(merge `05287e2`, 2026-10-16T14:36:13Z), 같은 PR로 들어간 Work #5 필수조건 독립 검증기(`tests/oracle`)는 Work #5 소관이다.

검증 경계: 아래 수치는 로컬 실제 PostgreSQL 17 테스트 전용 컨테이너(`serentable-foundation-pg`, 127.0.0.1:55432)에서 확인한 값이며 CI(`.github/workflows/ci.yml` verify job)가 같은 명령을 수행한다. 스위트 전체를 실행당 DB 스키마 재생성과 함께 개별 실행했고 `--repeat-each`는 쓰지 않았다(webServer 초기화가 실행당 1회라 상태 의존 스펙에서 거짓 실패가 난다).

- pytest **105 passed**, ruff check/format(CI 범위 `backend tests migrations`) PASS, 프런트 빌드 PASS.
- Playwright 전체 스위트 **9/9 PASS**(3회 개별 실행). 브라우저는 모바일 Chromium 에뮬레이션이며 실제 기기·배포 환경 검증이 아니다.
- CI: PR #27 head `f24ba46` [38915264719](https://github.com/InryeolChoi/SerenTable/actions/runs/38915264719), `c62a6ed` [38916165226](https://github.com/InryeolChoi/SerenTable/actions/runs/38916165226) SUCCESS.
- **미완료:** 배포 환경 브라우저 E2E(데모 계정 자격 증명이 세션에 없음), U03/U04 정책 확정. 매칭 실행기의 회차 `FOR UPDATE` 선행 조건은 Work #6 ①-b에서 충족했다(아래 Work #6 절).

### Blaybus에 반영할 Task 기록

아래 Task의 공통 위치는 `참가 신청·이용권·결제 > 일정 신청·이용권·모의 결제`다. 사용자가 각 Task의 기록란에 문구를 넣고 상태를 바꾸도록 요청한다. 실제 투입 시간은 사용자가 기록한다. 등록된 다섯 Task 중 네 개는 이미 구현·검증이 끝났고, 다섯째는 이번 PR #28의 범위다.

**Task: 모집 회차·지역 설정 — 완료 요청**

```text
수행 내용: 서울 4개 지역 고정 목록과 운영자의 회차 생성·조회 API·화면(회차 만들기·회차 목록, 서울 시각 표시)을 구현했습니다. 마이그레이션 0004_event_slot을 추가했습니다.
검증 결과: 실제 PostgreSQL에서 pytest 105 passed, Playwright 전체 스위트 9/9 PASS(3회 개별 실행), CI SUCCESS. 같은 지역·시작 시각 중복 생성 거절과 신청 마감 ≤ 매칭 예정 ≤ 시작 시각 검증을 화면 오류 알림으로 확인했습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/26 (닫힘, 내용이 #27로 통합) / https://github.com/InryeolChoi/SerenTable/pull/27 (병합)
추가 증거: https://github.com/InryeolChoi/SerenTable/actions/runs/38916165226
남은 작업: 회차 수정·취소는 후속 Work(매칭·재배치) 범위입니다. 배포 환경 브라우저 확인은 미완료입니다.
```

**Task: 일정 신청 — 완료 요청**

```text
수행 내용: 참가자가 모집 중인 회차를 후보로 복수 선택하고 검토 화면에서 확정해 제출한 뒤 내 신청 상태를 확인하는 흐름을 구현했습니다(선택 → 검토 → 제출 → 상태). 마이그레이션 0005_application을 추가했습니다.
검증 결과: 실제 PostgreSQL에서 pytest 105 passed, Playwright 전체 스위트 9/9 PASS. 필수 동의 누락·불완전 프로필 거절, 선택 유지, 같은 request_key 재제출이 같은 결과를 돌려주는 것을 시험으로 확인했습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/27 (병합)
남은 작업: 여러 후보 중 어느 회차로 확정되는지에 대한 후보 간 배정 규칙은 정책 확정 후 매칭 Work에서 다룹니다.
```

**Task: 이용권 · 모의결제 — 완료 요청**

```text
수행 내용: 1회권·멤버십 1/3/6개월 선택, 모의 결제(실패 시뮬레이션 포함)와 실패 후 재시도, 멤버십 기간 안의 무결제 신청, 보유 이용권 목록을 구현했습니다. U03 미확정 규칙은 화면에 '임시 적용 · 확정 전'으로 표시하고 마이그레이션 0006_payment를 추가했습니다.
검증 결과: 실제 PostgreSQL에서 pytest 105 passed, Playwright 전체 스위트 9/9 PASS. 결제 실패 1회가 기록된 뒤 재시도로 결제 완료, 후보 회차 시작 전에 끝나는 이용권 거절, 결제 마감 후 결제 차단, 취소된 신청에 묶여 보유되는 1회권을 시험으로 확인했습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/27 (병합)
남은 작업: U03 연장 단위·기산점, 멤버십 중복 구매·적용 범위, U04 시스템 실패 환불 예외는 CEO 답변 후 확정합니다. 실제 결제(PG) 연동은 범위가 아닙니다.
```

**Task: 실패·중복 요청 검증 — 완료 요청**

```text
수행 내용: 실패·중복·마감 시나리오를 실제 PostgreSQL HTTP 경계에서 검증하는 시험(tests/test_failure_and_duplicates.py)을 추가했습니다. 같은 request_key 재전송, 동시 제출, 마감 경과, 잘못된 입력을 다룹니다.
검증 결과: pytest 105 passed(해당 파일 포함), CI SUCCESS. 동시 제출이 정확히 한 건만 생성되는 것을 확인했습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/27 (병합)
남은 작업: 없음. 정책 확정이 필요한 항목은 '이용권 · 모의결제' Task에 적었습니다.
```

**Task: E2E 알림 단언 규약 정리 — 완료 요청**

```text
수행 내용: 한 화면에 같은 역할의 알림이 둘 이상 동시에 있을 수 있으므로, E2E 알림 단언을 문구나 알림을 담은 한 영역으로 좁히는 규약을 정하고 specs에 적용했습니다. 규약은 공통 헬퍼 frontend/e2e/support.ts에 기록했습니다. 테스트 전용 변경이며 제품 화면·API·정책·마이그레이션은 바꾸지 않았습니다.
검증 결과: Playwright 전체 스위트 9/9 PASS(3회 개별 실행), 실제 PostgreSQL에서 pytest 105 passed, ruff·프런트 빌드 PASS. 세션 철회 뒤 로그인 화면에서 화면 전역 alert locator가 2개를 잡아 strict mode로 실패하고, 폼으로 좁힌 locator는 1개를 잡아 통과하는 것을 실측했습니다(임시 진단 스펙은 실행 후 삭제, 커밋하지 않음).
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/28 (열림)
남은 작업: 없음. 배포 환경 브라우저 E2E는 계정 자격 증명이 없어 미완료입니다.
```

### Work #4 상태 판단

Work #4의 하위 다섯 Task는 위 문구대로 모두 완료로 바꿀 수 있다. 다만 Work 자체는 완료로 바꾸지 않기를 요청한다. U03/U04 정책 확정(CEO 답변 대기)과 배포 환경 브라우저 확인이 남아 있고, 후보 간 배정 규칙·회차 수정·취소는 후속 Work의 선행 조건이기 때문이다. Issue [#4](https://github.com/InryeolChoi/SerenTable/issues/4)의 체크박스와 Blaybus 상태는 사용자가 갱신한다(이 기록 시점에 아직 반영하지 않았다).

## Work #6 구현과 검증 결과

Work #6 `예약 매칭·재배치·실패 해결`(Agenda `자동 매칭·실패 해결`, GitHub Issue [#6](https://github.com/InryeolChoi/SerenTable/issues/6))의 진행 결과다. 등록된 두 Task 중 `자동 실행·확정·대안·이동/환불 구현`의 **앞부분만** 끝났고 두 Task 모두 완료가 아니다.

작업 분할은 사용자가 2026-10-17 승인한 계약([PR #30](https://github.com/InryeolChoi/SerenTable/pull/30), `docs/design/matching-contract.md`)을 따른다: ①-a 계약 → ①-b 자동 실행기 → ①-c 미매칭 대안·이동/보관/환불 → ② 신뢰성 검증. 계약이 승인한 결정은 **하드 제약만 사용**(테이블 4~6명·전원 결제·회차 동의·출생연도 차 ≤ 8·제외 쌍 없음·정원), **앉는 인원 최대화 후 제출 순서 tie-break**(U06 — 점수·성별 비율·MBTI는 U05 확정 전까지 쓰지 않음), **신청당 살아 있는 배치 하나·회차는 `matches_at` 오름차순·이미 다른 회차에서 확정된 신청 제외**(U07)다. 점수·재배치·환불은 이 범위에서 확정하지 않았다.

검증 경계: 아래 수치는 로컬 실제 PostgreSQL 17 테스트 전용 컨테이너(`serentable-foundation-pg`, 127.0.0.1:55432)에서 확인한 값이며 CI(`.github/workflows/ci.yml` verify job)가 같은 명령을 수행한다. Playwright는 webServer가 실행 전 스키마를 재생성하고 `--repeat-each`는 쓰지 않는다(초기화가 실행당 1회라 상태 의존 스펙에서 거짓 실패가 난다).

- ①-b 구현: `backend/serentable/matching.py`(하드 제약 플래너, 회차별 트랜잭션 실행기, 읽기 전용 운영자 이력), `migrations/versions/0007_matching.py`(`match_run`·`dining_table`·`table_assignment`·`match_run_member`·`match_participation`, `UNIQUE(event_slot_id, attempt)`·회차 `RUNNING` 부분 유니크·신청 살아 있는 배치 부분 유니크), `worker.py` 루프가 유일한 트리거(MAT-01: 공개 트리거·운영자 시작 없음), 참가자·운영자 화면에 저장된 매칭 축과 이력 표시.
- 신뢰성 동작: 회차 행 `FOR UPDATE` 후 **잠금 뒤 DB 시계**로 판정, 중단된 RUNNING 세대는 `stale_generation`으로 ABANDONED 후 attempt 2로 재개, 동시 실행 2개는 정확히 1개만 실행, 확정은 ①-b에서 최종이며 뒤 실행이 덮어쓰지 않음(U13 미결정), 매칭 축은 `match_participation`에 저장하고 `application.state`는 바꾸지 않음.
- pytest **115 passed**(신규 `tests/test_matching_runner.py` 10건 포함, 이전 105건 회귀 없음), ruff check/format(CI 범위 `backend tests migrations`) PASS, `npm run build` PASS, 마이그레이션 0007 up/down 왕복 확인.
- 독립 정답 대조: 같은 입력에서 플래너의 `seated_count`가 `tests/oracle/hard_constraints.py`의 `max_seatable()`과 정확히 같고 `validate_assignment()` 위반 0건, 같은 입력은 항상 같은 테이블이다(실행기는 오라클을 import하지 않는다).
- 실행기 실측(실제 PostgreSQL HTTP 경계): 결제 4명 → 테이블 1개·확정 4명, 미결제·3명 → `not_enough_eligible`, 1980년생 + 1994~96년생 → `age_gap`, 여러 회차 신청 → 가장 이른 회차 1곳에만 배치, 재실행 무시, 중단 세대 → attempt 2, 동시 실행 → 1건.
- Playwright 전체 스위트 **10/10 PASS**(실행기 로그 `worker_matching_ok runs=2`). 브라우저는 모바일 Chromium 에뮬레이션이며 실제 기기·배포 환경 검증이 아니다.
- CI: PR #31 head `d15cd78` [38929034129](https://github.com/InryeolChoi/SerenTable/actions/runs/38929034129) **SUCCESS**.
- 전체 스위트 첫 실행의 `payments.spec.ts:147` 실패는 원인을 실측으로 확인했다(실행 로그 `resolved to 3 elements`): 같은 DB를 공유하는데 이 스펙이 participant-03의 1회권을 2장 사서 이용권이 1→3으로 늘었다. 제품·테스트 로직은 바꾸지 않고 스펙 파일명을 `frontend/e2e/reserved-matching.spec.ts`로 바꿔 participant-03의 개수를 절대값으로 단언하는 `payments.spec.ts` 뒤에 실행되게 하고 이유를 파일에 적었다.
- **미완료:** Task ①-c(미매칭 대안·이동/보관/환불), U05 점수 도입, 실행 규모(U19·100명) 성능, 배포 환경 실행기 동작·브라우저 E2E(데모 자격 증명 없음), 계약 문서 76행 `UNIQUE(application_id)` → `WHERE ended_at IS NULL` 부분 유니크 문장 정정(PR #30 머지 후), ② 신뢰성 검증 Task.

### Blaybus에 반영할 Task 기록

Work #6의 두 Task 위치는 `자동 매칭·실패 해결 > 예약 매칭·재배치·실패 해결`이다. 아래 문구는 **부분 완료 보고**이며 Task를 완료로 바꾸지 않기를 요청한다. 실제 투입 시간은 사용자가 기록한다.

**Task: 자동 실행·확정·대안·이동/환불 구현 — 진행 중(부분 완료)**

```text
수행 내용: 승인된 매칭 계약(PR #30)의 앞부분을 실행했습니다. 매칭을 시작하는 공개 API도 운영자 시작 버튼도 없이 별도 실행기 루프만이 마감된 회차를 확정하도록 했고(MAT-01), 하드 제약(테이블 4~6명·전원 결제 완료·회차 동의·출생연도 차 8 이하·제외 쌍 없음·정원)만으로 앉는 인원을 최대화한 뒤 제출 순서로 tie-break하게 했습니다. 한 신청의 살아 있는 테이블 배치는 하나로 제한하고(DB 부분 유니크 인덱스) 회차는 매칭 예정 시각 오름차순으로 처리해 여러 후보 회차를 낸 신청은 가장 이른 회차에서만 앉습니다. 회차별 한 트랜잭션, 회차 행 FOR UPDATE 후 잠금 뒤 DB 시계 판정, 중단된 실행 세대 정리 후 재개, 동시 실행 1건 보장을 구현했고, 참가자 "내 신청"과 운영자 "신청 현황"에 저장된 매칭 상태·이유·실행 이력을 읽기 전용으로 표시했습니다. 마이그레이션 0007_matching을 추가했습니다.
검증 결과: 실제 PostgreSQL에서 pytest 115 passed(신규 매칭 10건 포함, 이전 105건 회귀 없음), ruff check/format PASS, 프런트 빌드 PASS, Playwright 전체 스위트 10/10 PASS, 마이그레이션 up/down 왕복 확인. 같은 작은 입력에서 배정 인원이 독립 정답 검증기 tests/oracle/hard_constraints.py와 정확히 일치하고 위반이 0건임을 시험으로 확인했습니다. 미배정 이유(인원 부족·출생연도 없음·나이 차·정원), 동시 실행기 경합, 중단 세대 재개를 실제 DB에서 확인했습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/31 (열림) / 계약: https://github.com/InryeolChoi/SerenTable/pull/30 (초안, 머지 대기)
추가 증거: https://github.com/InryeolChoi/SerenTable/actions/runs/38929034129
남은 작업: 미매칭 대안 제안·이동/보관/환불(①-c), 매칭 점수 도입(U05 확정 후), 배포 환경 실행기 동작 확인. 이 Task는 아직 완료가 아닙니다.
```

**Task: 필수조건·중복·중단 복구 검증 — 진행 중(착수 전)**

```text
수행 내용: 착수 전입니다. ①-b에서 필수조건·중복 배치·중단 복구의 실행기 동작과 오라클 대조는 확인했지만, 이 Task의 독립 검증 범위(재배치·확정 후 취소·대안·환불 상태 경합과 복구 전 과정)는 아직 시작하지 않았습니다.
검증 결과: 해당 없음(위 ①-b 검증은 구현 단계 검증이며 이 Task의 독립 검증이 아닙니다).
관련 PR: 해당 없음
남은 작업: Task ①-c 구현 후, 매칭 실행 권한·복수 회차 경합·이동과 환불 동시 요청·실행기 재시작 복구를 독립 검증으로 확인합니다.
```

### Work #6 상태 판단

Task `자동 실행·확정·대안·이동/환불 구현`은 **진행 중**으로 둔다. 자동 실행·확정은 구현·검증됐지만 ①-c(미매칭 대안·이동/보관/환불)와 U05 점수가 남아 있다. Task `필수조건·중복·중단 복구 검증`도 진행 중이며, ①-c 이후에 본격 착수한다. Work #6 자체도 부분 완료이므로 완료로 바꾸지 않기를 요청한다. Issue [#6](https://github.com/InryeolChoi/SerenTable/issues/6)의 체크박스와 Blaybus 상태는 사용자가 갱신한다(이 기록 시점에 아직 반영하지 않았다).
