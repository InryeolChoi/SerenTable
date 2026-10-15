# 배포 안전장치·원격 작업 검증

위치: 개발·배포 기반 확보 → 첫 배포·CI·DB 연결 → 배포 안전장치·원격 작업 검증. Task [#16](https://github.com/InryeolChoi/SerenTable/issues/16), 부모 Work [#2](https://github.com/InryeolChoi/SerenTable/issues/2).

검증 기준: 2026-10-16, Asia/Seoul. 조회 결과는 해당 시점의 관측이며 상시 모니터링이나 제품 업무 기능의 완료를 의미하지 않는다. 비밀값·개인정보·원본 데이터는 기록하지 않는다.

## 확인 결과

| 항목 | 실제 근거 | 판정 |
|---|---|---|
| 실패 CI 배포 차단 | [기존 실패/복구 실험](./ci-gate-verification.md). 실패 CI에서 API·worker 모두 SKIPPED, 복구 CI에서 모두 SUCCESS | 완료, 재실험 생략 |
| 배포 소스·CI 대기 | Railway 연결 도구의 실제 config에서 API·worker 모두 `main`, `source.checkSuites=true` | 확인 |
| API·DB·worker 실행 | 환경 상태 세 서비스 online, 실행 replica 각 1개, pendingWork 없음 | 확인 |
| 공개 HTTP | `/api/health` 버전 `cef5df16d5adec5fbc3545ae892542341571bb18`, `/api/readiness` DB connected, `/api/worker-health` alive. 모두 HTTP 200 | 확인 |
| worker 명령 위치 | Start `python -m serentable.worker`, Pre-deploy 빈 배열. API Pre-deploy는 `alembic upgrade head` | 확인 |
| 배포 준비 검사 경로 | 비어 있던 API healthcheckPath를 `/api/readiness`, timeout 300초로 설정. 기존 main 이미지 재배포 SUCCESS·실행 replica 1개 확인 | 보완 및 확인 |
| 비용 제어 | 사용자 00:29 화면: Hobby, 10/15~11/15 기간 Current Usage $0.00, Included Usage $5.00, Estimated Bill $0.00. Agent 한도 $5.00은 Compute 한도와 별개. 실제 Compute 알림/중단 한도는 미확인 | 일부 확인 |
| Railway 백업 | 사용자 00:30 Postgres Backups 화면: No Backups, 신규/예약 백업·PITR에 Pro 업그레이드 필요 안내. 해당 계정에서 예약 백업이 가능하다고 가정하지 않음 | 부재·플랜 제약 확인, 대체 복구 경로 미실행 |
| 로컬 복원 | [기존 실제 복원 기록](../design/implementation-progress.md): 별도 빈 DB 복원 뒤 API·worker 응답 확인 | 완료, 클라우드 백업의 증거로 대체하지 않음 |
| 모바일 원격 지시 | 접속 가능 사용자 확인 및 `REMOTE-20261016` 지시 수신 → commit `73c056b` → PR #20 → CI 38760875571 success | 완료 |

배포 조회: API `1875757c-c8a2-4276-92a9-b5936a89eb6a`, worker `4b7593f9-d758-4488-b13a-f7a681828be4`, Postgres `824f2670-2e44-4738-8e6d-cabde697b5be`가 SUCCESS였다. API·worker 각 실행 replica 1개를 함께 확인했으며 heartbeat만으로 배포 성공을 판단하지 않았다.

API는 Southeast Asia, DB도 Southeast Asia, worker는 US West에 있다. 지역 통일은 지연·전송비 검토 후 수행할 보완 후보이며 이번 조회에서 변경하지 않았다.

API healthcheck 보완 후 배포는 `7c88059a-0748-4f17-bc8b-93f0bb5154d6`로 SUCCESS였다. 적용된 설정을 다시 조회해 `/api/readiness`·300초를 확인했다. 같은 main 이미지를 재사용했고 source main/checkSuites=true를 유지했다. readiness가 통과하기 전 트래픽 전환을 막기 위한 배포 시점 검사이며 상시 장애 감시는 아니다. 이 외 클라우드 설정은 변경하지 않았다. 근거: [Railway healthcheck](https://docs.railway.com/deployments/healthchecks).

## 원격 지시에서 PR·CI까지

사용자가 휴대폰에서 이 대화에 접속 가능하다고 답했고, 요청한 원격 검증 문장 `원격 검증 실행: REMOTE-20261016`을 보냈다. 이를 해당 사용자 보고에 근거한 기기 검증으로 기록한다. 에이전트가 휴대폰 화면·기종·OS를 직접 관측한 것으로 표시하지 않는다.

| 단계 | 증거·범위 |
|---|---|
| 모바일 접속 | 사용자 답변: 휴대폰에서 이 대화에 원격 접속 가능 |
| 원격 지시 수신 | 이 대화의 `REMOTE-20261016` 요청 |
| 호스트 작업 | Task 전용 `codex/task16-deployment-safety`에서 이 검증 기록 작성·커밋 |
| GitHub 연결 | commit `73c056b5b64ccd129ee7c9c5fedfd0ab907fbab7`, [Task 전용 PR #20](https://github.com/InryeolChoi/SerenTable/pull/20) |
| CI | 해당 커밋의 [GitHub Actions 38760875571](https://github.com/InryeolChoi/SerenTable/actions/runs/38760875571) verify SUCCESS |

원격 작업 중에도 호스트의 저장소·인증·승인·도구 권한을 사용한다. 호스트가 절전·오프라인이거나 앱이 종료되면 이 경로가 중단될 수 있다. 새 비밀값을 휴대폰 대화에 붙여 넣는 방식으로 연결하지 않는다. 공식 근거: [OpenAI 원격 연결](https://learn.chatgpt.com/docs/remote-connections).

## 남은 운영 확인을 완료하는 방법

### 비용

1. [Workspace Usage](https://railway.com/workspace/usage)에서 이 프로젝트가 속한 workspace와 결제 기간, 현재 사용량을 확인한다.
2. Set Usage Limits에서 Compute의 Custom email alert와 Hard limit 값을 확인한다. Railway Agent의 사용량 한도는 앱 실행 비용 한도와 별개다.
3. 실제 값과 확인 시각을 기록한다. 아직 없는 한도를 임의로 설정하지 않고, 원화 예산과 환율·청구 범위를 확인하여 결정한다. hard limit 도달 시 workload가 중단된다.
4. 가동 첫 24시간 실제 사용량과 이후 일별 추이를 기록하여 예산 목표를 점검한다. 일시점의 적은 사용량으로 월 비용을 보장하지 않는다.

현재 Railway 연결 도구에는 비용·백업 조회 수단이 없고 로컬 Railway CLI는 설치되지 않았다. Safari 화면 조작은 사용자 입력과 겹쳐 중단되었고 사용자가 두 화면을 제공했다. 그 화면의 금액·플랜·백업 부재를 위 표에 반영했으며, Compute 한도 미확인을 미설정으로 단정하지 않는다. 현재 사용량 $0.00 표시만으로 최종 청구가 무료라고 결론내리지 않는다.

### 백업·복원

1. 현재 계정은 Hobby이며 제공 화면에서 Pro 기능 제한을 확인했다. 기존 실행 지침의 예약 백업 항목은 해당 계정에서 사용 가능하다는 보장이 아니다. 이번 Task에서 유료 플랜을 변경하지 않았다.
2. 제안: 예산 목표를 유지하고 우선 논리 백업·별도 DB 복원 경로를 마련한다. 실제 Railway 데이터의 백업을 가져올 인증된 실행 경로와 접근 제한 저장 위치·주기는 아직 미정이다. 원본 DB 비밀번호를 대화나 공개 GitHub에 넣지 않는다.
3. [실행 지침](./foundation-runbook.md)의 논리 백업을 별도 빈 테스트 DB로 복원하여 API readiness·worker와 복원할 업무 데이터의 수/제약을 확인한다. 현 단계에는 heartbeat 외 업무 데이터가 없다.
4. Railway의 기존 운영 volume에 Restore를 실행하면 대상 데이터를 덮어쓸 수 있다. 이번 Task에서 운영 DB 복원·서비스 삭제·새 유료 서비스 생성은 수행하지 않았다. 클라우드에서의 복구 목표·허용 중단 시간은 U18/U20의 남은 운영 결정이다.

공식 CLI에는 `railway postgres pitr backup list`, `railway postgres pitr schedule list`, `railway usage limit status` 조회 수단도 있다. 향후 설치·정상 인증 후 프로젝트·환경·서비스를 명시해 사용할 수 있으며, 이 기록에서 해당 명령을 실행했다고 주장하지 않는다.

## 완료 판단과 Blaybus 기록

Compute 한도와 Railway 데이터의 대체 백업·복원 준비가 남아 있으므로 Task #16과 부모 Work #2는 진행 중으로 유지한다. 모바일 원격 지시→PR→CI는 완료했다. 이 PR만으로 Work 전체를 자동 종료하지 않는다. 현황 문구와 실제 PR 링크를 사용자가 Blaybus 해당 Task에 기록한다. 실제 투입 시간은 사용자가 기록한다.

## 공식 근거

- [Railway 비용 제어](https://docs.railway.com/pricing/cost-control): Compute/Agent 한도 구분과 hard limit의 서비스 중단 효과.
- [Railway 백업](https://docs.railway.com/volumes/backups): volume 백업·복원과 예약.
- [Railway PostgreSQL CLI](https://docs.railway.com/cli/postgres): 조회와 운영 데이터 덮어쓰기의 구별.
- [OpenAI 원격 연결](https://learn.chatgpt.com/docs/remote-connections): 휴대폰 지시와 호스트 자원·접속 조건.
