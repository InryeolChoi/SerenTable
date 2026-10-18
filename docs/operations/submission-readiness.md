# 제출 준비 점검표

작성: 2026-10-19 (Asia/Seoul). 위치: **운영자 예외·최종 검증·제출 → 통합 검증·제출 (#10)**, Task 「테스트 계정·배포 링크·증거 제출 준비」. 이 문서는 제출 전에 확인할 항목과 근거 위치를 모은 점검표이며, 제출 완료나 배포 인수 완료를 뜻하지 않는다. 비밀번호·DB URL·개별 응답은 적지 않는다.

## 1. 배포 링크와 계정

| 항목 | 현재 상태 | 근거 | 남은 일 |
|---|---|---|---|
| 공개 URL | https://chanceplate.up.railway.app (Work #4 범위까지 배포 검증) | [신청·모의 결제 배포 검증](./application-deployment-verification.md) | Work #6~#9 migration 0009~0014·코드 운영 반영은 **사용자 승인 전** |
| 참가자 계정 | `participant-01`~`participant-04` (합성) | [운영 지침](./foundation-runbook.md) `seed_demo_accounts` | 심사위원에게 전달할 비밀번호를 비밀 환경 변수로만 관리하고 별도 경로로 전달 |
| 운영자 계정 | `operator` (합성, 단일 운영자 역할) | 같은 곳 | 운영자 역할 분리는 미정 정책 |
| 데모 시나리오 데이터 | 합성 100명 계정·프로필(A안)과 합성 동의·신청·모의 결제(B안) | [합성 시나리오 계약](../design/synthetic-demo-scenario-contract.md) | 운영 DB 적재는 별도 승인. 원본 `data/`는 적재하지 않음 |
| 결과 안내까지 접속 유지 | 미확인 | — | 비용·가용성 점검([PostgreSQL 복구](./postgres-recovery.md) 비용 절) 후 유지 기간 확인 |

## 2. 검증 증거 위치

| 범위 | 로컬·CI 자동 근거 | 배포 환경 |
|---|---|---|
| PRD 12단계 | [12단계 근거 매트릭스](../design/twelve-step-acceptance-matrix.md), `tests/test_twelve_step_flow.py`(한 회차 1→12 정상 흐름 연결) | **미완료** (운영 미반영) |
| 100명 측정 | [100명 측정 기록](../design/matching-scale-measurement-2026-10-19.md), `tests/test_matching_scale.py`, `tests/test_scale_measurement.py` | 배포 환경 시간·메모리 미측정 |
| 작은 데이터 독립 정답 | `tests/oracle/`, [매칭 정답 기준](../design/matching-oracle.md) | 해당 없음 |
| 권한·개인정보 | [보안 검증 계획](../design/security-verification-plan.md), `tests/test_auth.py`·`test_profile.py`·`test_operator_audit.py` 등 | 인증 공개 URL 검증은 Work #3 범위까지 |
| 중복·중단 복구 | `tests/test_failure_and_duplicates.py`, `test_matching_runner.py`(동시 실행·롤백), `test_mock_refund_retry.py`, worker 강제 종료 시험(PR #35) | 미확인 |
| DB 백업·복원 | [PostgreSQL 복구](./postgres-recovery.md), CI 격리 PG18 백업·복원 단계 | Railway 실제 백업·격리 복원 기록 참조 |
| 운영자 예외·복구 | [Work8·9 검증](../design/work8-work9-verification-2026-10-18.md), [운영 복구 검증](../design/operator-recovery-verification-2026-10-19.md) | 미완료 |

## 3. 제출 전 사용자 결정·직접 작업

1. 열린 PR(#39, #41 및 후속 통합 PR) 검토와 main 병합 순서 결정. main 병합은 Railway 자동 배포를 시작할 수 있다.
2. 운영 migration·deploy 승인과 배포 후 공개 URL 12단계 재현(심사위원 계정으로).
3. 실제 휴대폰 푸시 구독·수신 인수(권한 허용/거부·미지원 포함). 가짜 공급자 성공은 실기기 수신이 아니다.
4. 미정 정책: U16 감사·신고·개인정보 보관, 운영자 역할 분리, 운영 조치 사유 입력, U19 100명 초과 입력·탐색 중단 처리.
5. 100명 측정에서 나온 결정 후보: 정원 때문에 남은 신청의 미배정 이유 표기(`capacity` 대신 `no_valid_table`), 느린 기계에서 탐색 시간 보호로 배정 수가 줄 수 있는 문제.
6. Blaybus 각 Task에 실제 PR 링크·수행/검증 문구를 수동으로 기록.

## 4. 제출 시 구분해 적을 것

- 실제 예약 실행(운영 worker)과 시험 고정 장치의 시각 이동을 구분한다.
- 실기기 푸시와 모의·가짜 공급자 경로를 구분한다.
- 로컬·CI 통과와 배포 환경 통과를 구분한다. 미완료 P0를 완료로 적지 않는다.
