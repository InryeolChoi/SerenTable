# MVP 구현 분류 및 실행 기록

기준: 2026-10-15, Asia/Seoul. 사용자가 `implement-spec`으로 현재 구현 가능한 작업의 분류와 실행을 요청했다. 앞선 10/16 시작 계획보다 최신 구현 시작 요청을 우선한다. 기본 순서는 Agenda → Work → Task를 유지한다.

## 작업 위치와 브랜치

- 통합 브랜치: `integration/mvp`.
- 기준 커밋: 원격 main의 `b92b1d6`. 명세 PR #11이 병합된 상태에서 시작했다.
- 현재 Work: 개발·배포 기반 확보 → 첫 배포·CI·DB 연결, GitHub Issue #2.
- 구현자는 별도 작업 트리/브랜치에서 승인된 외부 행동 경계를 대상으로 TDD를 진행한다. 구현 후 통합 브랜치에 병합하고 독립 검증·리뷰를 수행한다.

## 분류

| Work | 상태 | 현재 실행 범위 또는 선행 조건 |
|---|---|---|
| #1 요구사항·설계·자료 정리 | 완료 | PR #11 병합, 세 Task의 문서·승인 검증 경계·자료 검토 확인. Issue 종료 |
| #2 첫 배포·CI·DB 연결 | 일부 Task 완료, 배포 대기 | 화면·API·실제 PostgreSQL·마이그레이션·실행기·CI 기반 구현 및 로컬 검증 완료. Railway 외부 계정/프로젝트 설정과 실기기·원격 검증은 미완료 |
| #3 로그인·프로필·동의 | 대기 | #2 인수 기준 및 U01/U02/U16의 제품 정책 확정 필요. 라이브러리 등 일반 기술 선택과 사업 정책을 구분 |
| #4 일정 신청·이용권·모의 결제 | 대기 | #3, 모의 구독·환불·취소 정책 U03/U04 필요 |
| #5 규칙·데이터·정답 기준 | 정책 결정 필요 | 기술적으로는 #1 완료로 자료 검토 가능하나 기본 순서는 #4 다음. U05~U09/U14/U17/U19 확정 필요 |
| #6 예약 매칭·재배치·실패 해결 | 대기 | #4/#5, 상태 경쟁·재시도·확정 후 취소 범위 필요 |
| #7 식당·채팅·알림 | 대기 | #6, 음식/가격 검증·채팅/푸시·재시도 기준과 실제 기기 확인 필요 |
| #8 참석·피드백·다음 추천 | 대기 | #7, 피드백·신고·체크인·공개/보관 정책 필요 |
| #9 운영자 예외·안전 종합 관리 | 대기 | #8. 기본 권한·운영 설정·예외 처리는 이전 기능 Work와 함께 구현 |
| #10 통합 검증·제출 | 대기 | #9 및 배포·기기·데모·정량 수용 기준 검증 |

## 외부 접근과 검증 조건

- 로컬 Docker Desktop을 시작했고 Docker 서버 `29.8.2`를 확인했다. 실제 PostgreSQL을 사용한 통합 테스트를 준비한다.
- 초기 확인에서 Railway CLI와 로컬 로그인 설정은 없었다. 실제 배포·과금·서비스 생성이 수행되었다고 기록하지 않는다.
- 제품 동작에 영향을 주지 않는 런타임·의존성·검사 도구 선택은 구현자가 근거와 함께 정리한다. 구독·매칭·신고 등 사업 정책을 임의로 확정하지 않는다.
- 실제 사용자 시간은 추정하지 않는다. 테스트 결과와 실행 환경·미완료 조건을 분리해 기록한다.

## Blaybus 수동 갱신 요청

완료한 Work #1: `개발·배포 기반 확보 > 요구사항·설계·자료 정리`의 세 Task에 PR #11을 연결한다. 요구사항 차이·데이터 검토·기술/미정 명세의 결과물을 확인한 뒤 Work를 완료로 바꾸도록 사용자에게 요청했다. 사용자 실제 반영 여부는 아직 확인하지 않았다.

현재 Work #2는 진행 중이다. 완료한 Task별 실제 PR·검증 근거는 아래에 제공한다. 다음 Work를 실행하거나 새 Work/Task를 추가할 필요가 생기면 이유·위치·완료 기준·일정 영향을 먼저 안내한다.

## Work #2 구현과 검증 결과

검토 산출물: [Draft PR #12](https://github.com/InryeolChoi/SerenTable/pull/12). 제품 기능이나 Work 전체 완료를 뜻하지 않는다. 관련 실행 지침은 [첫 배포 실행 지침](../operations/foundation-runbook.md)이다.

- Python 3.12·Node 22·PostgreSQL 17, uv 잠금 파일, SQLAlchemy/psycopg·Alembic을 기반 도구로 선택했다. U18 중 런타임·DB 도구·자동 검사 구성만 구현했고 외부 운영 설정은 남아 있다.
- React CSR의 홈·참가자·운영자 준비 화면을 FastAPI 이미지에 포함한다. 로그인·관리자 권한·업무 데이터는 아직 없다.
- liveness, PostgreSQL 실제 query 기반 readiness, 별도 실행기의 heartbeat 관측 API를 제공한다. worker는 연결 확인용이며 예약 매칭·알림 엔진을 구현한 상태가 아니다.
- 실제 PostgreSQL HTTP 통합 **7개**, 모바일 크기 Chromium **1개**, Ruff 검사, Node22/Python3.12 Docker 빌드가 통과했다. TDD에서 API/화면 미구현 404와 worker 모듈 부재 실패를 확인한 뒤 구현했다.
- Compose의 앱·DB·worker 실행과 readiness/worker-health 200을 확인했다. 별도 브라우저에서도 참가자 경로 이동·새로고침을 확인했다.
- 커밋 `1029210`의 [GitHub push CI](https://github.com/InryeolChoi/SerenTable/actions/runs/38740355994)가 실제 통과했다. PR·`main`·`integration/mvp` push에서 DB 마이그레이션·HTTP·화면·이미지 검사를 수행한다.
- 로컬 DB를 `pg_dump`로 백업하고 별도 빈 `serentable_restore_work2` DB에 복원했다. 복원 DB의 API readiness 200과 별도 worker 실행 후 worker-health 200을 확인했다. Railway 백업 설정·복원 검증과는 별개다.
- 독립 Standards 리뷰는 지적 0건이었다. Spec 리뷰에서는 로컬 테스트 DB 설정 명령 누락 1건을 발견하여 실행 지침을 보완했다. 보완한 환경변수·마이그레이션·테스트 명령으로 HTTP 7개 통과를 다시 확인했다.
- 사용자가 Railway는 아직 연결하지 않았다고 확인했다. 실제 배포 Task는 계정 연결 후 재개하며, 후속 Work를 완료한 것으로 처리하지 않는다.

### Blaybus에 반영할 Task 기록

두 Task의 공통 위치는 `개발·배포 기반 확보 > 첫 배포·CI·DB 연결`이다. 사용자가 각 Task의 작업 내용 기록란에 아래 문구를 넣고 완료 상태로 바꾸도록 요청한다. 실제 투입 시간은 사용자가 기록한다.

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

**Task: Railway 배포 및 모바일 검증 — 진행 중**

```text
수행: 동일 이미지의 API/worker와 PostgreSQL 구성, GitHub Wait for CI, 명령·환경변수·healthcheck·비용·백업·원격 검증 절차를 문서화했습니다.
남은 사항: Railway 계정 연결/실제 배포, CI 실패 배포 차단, 실제 휴대전화 접속, 모바일 Codex 원격 작업, Railway 비용·백업 설정 및 복원 검증입니다. 모바일 크기 자동 테스트를 실기기 검증으로 대체하지 않습니다.
관련 PR: https://github.com/InryeolChoi/SerenTable/pull/12
```

Work #2와 Agenda는 완료 처리하지 않는다. Task 추가나 등록 트리 수정은 없다.
