# MVP 구현 분류 및 실행 기록

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
| #6 예약 매칭·재배치·실패 해결 | 대기 | #4/#5, 상태 경쟁·재시도·확정 후 취소 범위 필요 |
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
