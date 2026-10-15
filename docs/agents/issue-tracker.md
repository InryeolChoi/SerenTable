# 프로젝트 이슈 트래커

이 프로젝트의 이슈 트래커는 GitHub Issues이며 저장소는 [InryeolChoi/SerenTable](https://github.com/InryeolChoi/SerenTable)이다. 사용자 승인에 따라 Blaybus Work 하나를 GitHub Issue 하나에 연결한다.

- Issue 조회·생성·수정은 GitHub 도구 또는 `gh` CLI를 사용한다.
- 기본 구현 순서는 등록한 Agenda → Work → Task이다. Work Issue의 직접 차단 관계와 정책 선행 조건을 함께 확인한다.
- Task와 PR은 강제 1:1이 아니다. PR은 해당 Work Issue와 Task를 명시한다. 부분 Task 완료 PR에서 전체 Work를 자동 종료하지 않는다.
- Work 인수 기준을 모두 충족했을 때 Issue를 종료한다. 미완료 배포·실제 기기 검증·정책은 미완료로 표시한다.
- 사용자에게 Task 완료마다 Blaybus 위치·붙일 수행/검증 문구·실제 PR 링크를 제공한다. Work 완료나 Agenda 변경도 조건 충족 시 요청한다. 사용자가 Blaybus를 수동 갱신한다.
- 외부 PR을 별도 요구사항 접수 표면으로 사용하지 않는다.

## 2026-10-16 네 Task 병렬 실행 예외

사용자가 지정한 네 Task에 한해 각각 별도 Issue·PR을 만든다. 부모 Work #2·#15는 유지하며 Task Issue #16~#19를 하위 이슈로 연결한다. 배포 검증과 공통 설계 준비를 병렬로 진행하도록 승인했으나 부모 Work의 미완료 인수 기준이나 후속 기능의 정책 선행 조건이 해소된 것은 아니다.

| Task | Issue | 부모 Work |
|---|---|---|
| 배포 안전장치·원격 작업 검증 | #16 | #2 |
| 핵심 ERD·상태·무결성 제약 설계 | #17 | #15 |
| 공통 UI·핵심 화면 흐름 설계 | #18 | #15 |
| 개인정보·권한·보안 검증 기준 정리 | #19 | #15 |

각 PR은 해당 Task Issue를 참조한다. 실제 인수 기준이 남은 Task는 Draft와 열린 Issue로 유지한다. 부모 Work는 자동 종료하지 않는다. 기존 계획 PR #13을 선행 기반으로 하고 네 Task PR의 변경은 따로 검토한다. 통합 브랜치는 `codex/core-design-integration`이다.

근거는 사용자 승인된 설계 인터뷰, 구현 명세, Work별 Issue 발행 계획과 최신 지시다. 초기 setup 대화의 미응답 로컬 마크다운 추천은 적용하지 않는다.
