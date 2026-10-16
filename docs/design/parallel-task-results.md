# 네 Task 병렬 실행 결과

기준: 2026-10-16, Asia/Seoul. 사용자가 지정한 네 Task를 각각 별도 Issue·PR로 진행했다. 원래 Work Issue #2/#15를 유지하고 GitHub 하위 이슈로 연결했다. 실행 중 새 Work나 Task를 추가하지 않았다.

## 위치와 결과

공통 Agenda는 **개발·배포 기반 확보**이다.

| Work → Task | Issue | PR | 현재 결과 |
|---|---|---|---|
| 첫 배포·CI·DB 연결 → 배포 안전장치·원격 작업 검증 | [#16](https://github.com/InryeolChoi/SerenTable/issues/16) | [#20](https://github.com/InryeolChoi/SerenTable/pull/20) | 사용자 PR 머지 확인. Task는 진행 중: Compute 한도·실제 Railway 데이터 백업 경로 미완료 |
| 핵심 데이터·화면·보안 설계 → 핵심 ERD·상태·무결성 제약 설계 | [#17](https://github.com/InryeolChoi/SerenTable/issues/17) | [#23](https://github.com/InryeolChoi/SerenTable/pull/23) | 설계 산출물 작성·검토 완료. 사업 정책 승인·DB 제약 적용과 구분 |
| 같은 Work → 공통 UI·핵심 화면 흐름 설계 | [#18](https://github.com/InryeolChoi/SerenTable/issues/18) | [#22](https://github.com/InryeolChoi/SerenTable/pull/22) | 흐름·스케치 검토 완료. 사용자 후속 요청의 로고 대조에서 직접 미반영 확인, 브랜드 보완 필요 |
| 같은 Work → 개인정보·권한·보안 검증 기준 정리 | [#19](https://github.com/InryeolChoi/SerenTable/issues/19) | [#21](https://github.com/InryeolChoi/SerenTable/pull/21) | 사용자 PR 머지 확인, 검증 기준 설계 완료. 실제 제품 보안 시험 통과와 구분 |

ERD·UI·보안은 각각 전용 작업 트리의 구현 에이전트가 담당하고, 배포 검증은 주 에이전트가 담당했다. 별도 병합 에이전트가 `codex/core-design-integration`에서 결과를 통합했다. 제품 코드·업무 마이그레이션·원본 자료의 변경/적재는 없으며 `.gitignore`의 `/data/` 보호 규칙을 추가했다.

## 검증과 한계

- ERD: PRD 신청/결제/매칭/참석 상태 3/8/8/5개 대조, 3개 Mermaid SVG 실제 렌더링 성공. 소유권·회차 후보·이동·무결성 책임과 U 결정점을 검토했다.
- UI: 로컬 Chrome 360×800·1440×1000에서 신청 오류·후보 쌍·상태/실패 해결·텍스트 대화 시뮬레이션·피드백·운영자 예외와 가로 넘침·키보드 이동을 확인했다. 실제 기기나 제품 API E2E의 통과는 아니다.
- 보안: 현재 코드·이미지·CI 읽기 전용 검토, 공개 준비 화면·상태 API 200 및 제한된 비공개 경로 404 관찰, ignore 규칙 확인. 인증/세션·CSRF/XSS·CSV·객체 권한의 실제 제품 시험은 후속 기능 Work에서 수행한다.
- 운영: CI 실패 차단 기존 실험, main 서비스 SUCCESS·replica 각 1개·상태 API, 모바일 요청 → commit `73c056b` → PR #20 → [CI 성공](https://github.com/InryeolChoi/SerenTable/actions/runs/38760875571)을 확인했다. API readiness healthcheck를 설정하고 기존 이미지 재배포 성공도 확인했다.
- 사용자 제공 화면: Hobby 사용량 $0·포함 사용량 $5, Agent 한도 $5, Postgres 백업 부재와 Pro 기능 제한을 확인했다. Compute 한도는 별도 확인이 필요하다. Pro 전환·결제·운영 DB 복원은 수행하지 않았다.

독립 리뷰 범위는 `4f41619...6357379`이며 Standards 0건, Spec 0건이었다. 발견한 문서 후행 공백과 렌더링 증거 연결은 단일 수정 에이전트가 보완했다. 이후 사용자 요청으로 PR #23에 SVG·PNG 3장씩과 확대 뷰어, PR #22에 로고 자료 대조를 추가했다. 이 후속 변경은 기존 리뷰의 검토 범위와 구분한다. 사용자 제공 화면과 원본 자료는 공개 저장소에 첨부하지 않는다. 실제 투입 시간은 사용자가 기록한다.

## PR 검토·병합 순서

네 Task PR은 공통 준비 문서 PR [#13](https://github.com/InryeolChoi/SerenTable/pull/13)의 브랜치를 기준으로 한다. 사용자가 #20과 #21을 해당 브랜치에 머지했고 #22/#23은 열린 상태다. #13은 아직 main에 머지되지 않았다. 문서 PR 머지를 제품 배포·Task 전체 인수 기준 충족으로 취급하지 않는다. Task #16의 운영 조건과 #18의 브랜드 보완은 남아 있으며 부모 Work 전체를 자동 종료하지 않는다.

## Blaybus에 붙일 기록

아래 문구와 관련 PR을 해당 Task의 작업 내용에 기록한다. 보안 검증 기준 설계는 사용자 PR 머지 확인에 따라 완료로 기록할 수 있다. ERD는 시각화 추가본을 검토하고 UI는 로고 반영 보완을 확인한다. 배포 검증은 진행 중을 유지한다. 이번 기록만으로 Work나 Agenda 전체를 완료하지 않는다. 사용자가 직접 반영하며 자동 동기화를 수행한 것은 아니다.

**첫 배포·CI·DB 연결 → 배포 안전장치·원격 작업 검증**

```text
수행: API·worker의 CI 대기/main 설정과 정상 실행을 확인하고 API readiness 배포 healthcheck를 보완했습니다. 휴대폰 지시 REMOTE-20261016을 전용 브랜치 commit·PR·CI 성공으로 연결했습니다. PR #20 머지 완료.
검증: 상태 API 200, 세 서비스 SUCCESS/replica 각1, 기존 실패 CI 배포 SKIPPED 증거 확인. Hobby 사용량·백업 부재/Pro 제약 확인.
남음: Compute 알림/중단 한도, 실제 Railway 데이터의 논리 백업·별도 복원 준비. 진행 중 유지.
PR: https://github.com/InryeolChoi/SerenTable/pull/20
```

**핵심 데이터·화면·보안 설계 → 핵심 ERD·상태·무결성 제약 설계**

```text
수행: 핵심 관계·독립 상태·회차 후보·권리/배치 소유권·무결성 및 트랜잭션 책임, 멱등·복구 제안을 정리했습니다.
검증: PRD 상태 대조, Mermaid 3개 렌더링, UI·권한 정의와 독립 검토 완료. 물리 스키마·사업 정책 확정이나 DB 적용 결과는 아닙니다.
PR: https://github.com/InryeolChoi/SerenTable/pull/23
```

**같은 Work → 공통 UI·핵심 화면 흐름 설계**

```text
수행: 참가자·운영자 공통 UI와 핵심 화면 흐름, 로딩/빈 상태/실패/거절 및 합성 스케치 6개 화면을 작성했습니다.
검증: 모바일/데스크톱 크기 Chrome에서 선택·상태·실패 해결·대화·피드백·운영자 시뮬레이션과 가로 넘침/키보드 이동을 확인했습니다. 실제 제품 기능은 후속 Work입니다.
PR: https://github.com/InryeolChoi/SerenTable/pull/22
```

**같은 Work → 개인정보·권한·보안 검증 기준 정리**

```text
수행: 역할 6종의 객체/필드별 권한, 세션·로그·CSV·합성 시드와 기능별 거절/경합 검증 기준을 작성했습니다. data 원본 실수 커밋 방지 규칙을 추가했습니다. PR #21 머지 완료, 검증 기준 설계 Task 완료.
검증: 현재 코드·공개 GET·ignore 규칙을 점검하고 독립 검토했습니다. 실제 인증/권한 보안 시험은 기능 구현 후 수행하며 U16 등 정책은 미결정입니다.
PR: https://github.com/InryeolChoi/SerenTable/pull/21
```
