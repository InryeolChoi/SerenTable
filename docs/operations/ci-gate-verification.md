# CI 실패 배포 차단 실제 검증

Task: 개발·배포 기반 확보 → 첫 배포·CI·DB 연결 → 배포 안전장치·원격 작업 검증

검증일: 2026-10-15, Asia/Seoul. 이 기록은 CI 차단 하위 항목이며 전체 Task 완료가 아니다.


앱 코드·DB를 변경하지 않고 잠시 codex/ci-gate-probe 브랜치를 두 서비스에 연결했습니다. main에는 실패 CI나 검증 워크플로를 병합하지 않았습니다.

| 단계 | commit | GitHub CI | API / worker Railway |
|---|---|---|---|
| 정상 기준 | c183f28 | success — https://github.com/InryeolChoi/SerenTable/actions/runs/38752960000 | 두 서비스 SUCCESS |
| 의도적 실패 | 2ac33e0 | failure — https://github.com/InryeolChoi/SerenTable/actions/runs/38754814142 | API 191379ff-9a57-4afb-8d00-89ff36ad9bd8 SKIPPED, worker cc372229-0dfc-4c64-a75c-ebcb604a0a39 SKIPPED; 빌드/실행 로그 없음 |
| 정상 복구 | 61088d8 | success — https://github.com/InryeolChoi/SerenTable/actions/runs/38754987811 | API 0055ae6a-c09b-4a7f-99ed-a4d87e46f1cc SUCCESS, worker 294a3568-ddb8-43c1-9c53-9fedaee04415 SUCCESS |

API·worker의 source.checkSuites=true 활성화를 실제 설정으로 확인했습니다. 두 서비스 모두 main·checkSuites=true로 복구했고 main 커밋 1407e23의 API/worker SUCCESS·실행 replica 각1개와 공개 health/readiness/worker-health 200을 확인했습니다. API 복구 배포 bcf890da-fd8a-4ad2-abbb-11fc78cced71, worker 복구 배포 521d10f8-8727-4fed-85ed-644785c6a416입니다. 임시 원격 브랜치는 삭제했고 실패 워크플로는 main에 병합하지 않았습니다. 이 결과로 CI 차단 하위 검증은 충족했으나 비용/백업 준비 및 모바일 Codex 검증이 남아 전체 Task/Work는 진행 중입니다.
