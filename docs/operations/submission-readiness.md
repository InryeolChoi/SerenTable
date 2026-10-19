# 제출 준비 점검표

작성: 2026-10-19 (Asia/Seoul). 위치: **운영자 예외·최종 검증·제출 → 통합 검증·제출 (#10)**, Task 「테스트 계정·배포 링크·증거 제출 준비」. 이 문서는 제출 전에 확인할 항목과 근거 위치를 모은 점검표이며, 제출 완료나 배포 인수 완료를 뜻하지 않는다. 비밀번호·DB URL·개별 응답은 적지 않는다.

## 1. 배포 링크와 계정

갱신: 2026-10-19 23:30 KST. 운영 배포 커밋은 main 최신(Work #6~#10, PR #46~#50 포함)이며 공개 URL에서 health 버전·readiness·worker-health로 확인했다.

| 항목 | 현재 상태 | 근거 | 남은 일 |
|---|---|---|---|
| 공개 URL | https://chanceplate.up.railway.app — Work #6~#10 코드·migration 0009~0014 운영 반영, readiness ready, worker 정상(DB와 같은 리전, 주기 약 2초) | [배포 12단계 검증](./deployed-twelve-step-verification.md) | 없음 |
| 참가자 계정 | `participant-01`~`participant-04` (합성). 매칭 관련 프로필 항목은 운영 검증 때 `--normalize-profiles`로 고정 합성값이 됨 | [운영 지침](./foundation-runbook.md) `seed_demo_accounts` | 비밀번호는 제출 양식의 계정 입력란으로 전달(사용자 결정). 저장소·문서에는 적지 않음 |
| 운영자 계정 | `operator` (합성, 단일 운영자 역할) | 같은 곳 | 운영자 역할 분리는 미정 정책 |
| 데모 시나리오 데이터 | 운영 DB에는 합성 4계정과 배포 검증 회차 2개(아래 2절)가 있음. 합성 100명 계정·프로필(A안)·동의·신청(B안)은 운영 미적재 | [합성 시나리오 계약](../design/synthetic-demo-scenario-contract.md) | 100명 데이터 운영 적재 여부는 별도 승인 |
| 실기기 푸시 | iPhone 홈 화면 앱 구독·잠금화면 수신 확인(시험 알림, 매칭 확정, 모임 시작 대화 주제) | [배포 12단계 검증](./deployed-twelve-step-verification.md) 운영 실행 결과 | Android/Chrome 실기기, 권한 거부·미지원 안내 화면 확인 |
| 결과 안내까지 접속 유지 | 미확인 | — | 비용·가용성 점검([PostgreSQL 복구](./postgres-recovery.md) 비용 절) 후 유지 기간 확인 |

## 2. 검증 증거 위치

| 범위 | 로컬·CI 자동 근거 | 배포 환경 |
|---|---|---|
| PRD 12단계 | [12단계 근거 매트릭스](../design/twelve-step-acceptance-matrix.md), `tests/test_twelve_step_flow.py` | **PASS**(2026-10-19, slot `8faf8481-…`, FAIL 0). 11단계 다음 매칭 반영 PASS(두 번째 slot `537191ce-…`, `new` 100.00→0.00). 후기 리마인드는 2026-10-20 22:34 이후 확인 예정 |
| 100명 측정 | [100명 측정 기록](../design/matching-scale-measurement-2026-10-19.md), `tests/test_matching_scale.py`, `tests/test_scale_measurement.py` | 배포 환경 시간·메모리 미측정 |
| 작은 데이터 독립 정답 | `tests/oracle/`, [매칭 정답 기준](../design/matching-oracle.md) | 해당 없음 |
| 권한·개인정보 | [보안 검증 계획](../design/security-verification-plan.md) A5-W2 절, `tests/test_authorization_sweep.py`(전 경로 역할·CSRF·객체 권한), `frontend/e2e/zzzz-authz.spec.ts` | 배포 12단계에서 비공개 값 비노출·외부인 방 거절·참가자 운영 API 403 확인 |
| 중복·중단 복구 | `tests/test_failure_and_duplicates.py`, `test_matching_runner.py`(동시 실행·롤백), `test_mock_refund_retry.py`, worker 강제 종료 시험(PR #35) | 배포 12단계에서 신청·결제·메시지·체크인 재전송 중복 없음 확인. 강제 종료 복구는 로컬·CI만 |
| DB 백업·복원 | [PostgreSQL 복구](./postgres-recovery.md), CI 격리 PG18 백업·복원 단계 | 2026-10-19 운영 백업과 격리 PG18 복원 성공(Work #6~#10 배포 전) |
| 운영자 예외·복구 | [Work8·9 검증](../design/work8-work9-verification-2026-10-18.md), [운영 복구 검증](../design/operator-recovery-verification-2026-10-19.md) | 운영에서는 정상 흐름의 "예외 0·운영자 조치 0"만 확인. 예외 해결 흐름은 로컬·CI 근거 |

## 3. 제출 전 사용자 결정·직접 작업

1. 미정 정책: U16 감사·신고·개인정보 보관, 운영자 역할 분리, 운영 조치 사유 입력, U19 100명 초과 입력·탐색 중단 처리.
2. 결과 안내까지 Railway 유지 기간과 비용 확인.
3. 합성 100명 데모 데이터를 운영에 적재할지 결정(적재 시 운영 DB 변경 승인 필요).
4. 후기 리마인드 운영 확인(2026-10-20 22:34 KST 이후 `check-feedback-reminder`). 운영 검증 실행 중에는 main 병합을 멈춘다(병합 시 API 재배포로 실행이 끊긴다).
5. Blaybus 각 Task에 실제 PR 링크·수행/검증 문구를 수동으로 기록.

해결된 항목(2026-10-19): main 병합 순서와 운영 migration·deploy 승인, 배포 환경 12단계 재현, iPhone 실기기 푸시 수신, 미배정 이유 `capacity` 표기와 탐색 상한 8초(PR #46), 심사위원 비밀번호 전달 경로(제출 양식).

## 4. 제출 시 구분해 적을 것

- 실제 예약 실행(운영 worker)과 시험 고정 장치의 시각 이동을 구분한다.
- 실기기 푸시와 모의·가짜 공급자 경로를 구분한다.
- 로컬·CI 통과와 배포 환경 통과를 구분한다. 미완료 P0를 완료로 적지 않는다.
