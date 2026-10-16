# 도구 간 작업 인계

마지막 기록: 2026-10-16, Asia/Seoul. Codex·Claude Code 및 다른 개발 에이전트가 도구 전환 시 읽는 공통 상태 기록이다. 아래 내용은 해당 시점의 스냅샷이며 시작 시 Git·GitHub·배포 상태를 재확인한다.

## 먼저 확인할 현재 상태

- 저장소: https://github.com/InryeolChoi/SerenTable
- 현재 주 작업 디렉터리: `/Users/inchoi/SerenTable`, 통합 브랜치 `codex/core-design-integration`. 공통 인계 문서 최초 커밋은 `a53ccc6`이고 루트 반영 커밋은 `d549f5f`이다. 이후 공통 기록 갱신 규칙을 보강했으며 문서 PR #13으로 전달한다. 실제 HEAD는 `git log`에서 확인한다.
- 이 통합 브랜치에는 아직 main에 없는 설계 산출물이 있다. 새 clone에서 main만 열고 해당 산출물이 없다고 판단하지 않는다. 이 문서가 포함된 통합 브랜치나 요청받은 Task PR 브랜치를 사용한다.
- **사용자 변경 보존:** 인계 작성 직전 루트 checkout에서 `docs/design/erd/index.html` 삭제와 `docs/design/erd/erd.html` 미추적 파일을 관찰했다. 파일명 변경으로 보이나 작성 의도는 확인하지 않았다. 이 변경을 복원·삭제·강제 stage하지 않았고 인계 문서 커밋에도 포함하지 않는다. ERD 링크를 수정할 Task에서 현재 파일과 사용자 의도를 확인한다.
- 사용자 마지막 방향은 오늘 제품 구현을 마무리하고 재개 때 이어가는 것이었다. 이번 요청은 도구 전환과 에이전트의 자율 기록 갱신 준비다. 다음 제품 Task를 자동 착수하거나 Claude 모델 세션을 대신 실행하지 않았다.

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
| 첫 배포·CI·DB 연결 → 배포 안전장치·원격 작업 검증 | #16 / PR #20 | 사용자 머지 완료, 단 `codex/sync-foundation-tasks`에 머지됨. 원격·CI·readiness 검증 완료. Compute 한도·Railway 데이터 백업 경로 미완료로 Task 진행 중 |
| 핵심 데이터·화면·보안 설계 → 핵심 ERD·상태·무결성 제약 설계 | #17 / PR #23 | 열린 PR. 문서·SVG/PNG 각3장·확대 뷰어와 생성 스크립트 제공. 최신 그림은 설계안이며 실제 DB 적용 아님 |
| 같은 Work → 공통 UI·핵심 화면 흐름 설계 | #18 / PR #22 | 열린 PR. 흐름/합성 스케치 검토 완료. 로고 직접 미반영 확인, CTO 표지의 갈색·크림색/원형 6인 식탁과 현재 버건디/사각 식탁의 차이를 ui-brand-review.md에 기록. 브랜드 보완 필요 |
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

## 다음 작업 순서

1. 미커밋 ERD 파일명 변경과 현재 PR/브랜치 확인. 인계 준비 자체를 제품 진척으로 세지 않는다.
2. Work #2의 Compute 예산 제어·실제 데이터 백업/복원 경로를 마무리한다. 명령 실행에 필요한 인증과 정책을 확인하고 기존 운영 DB 덮어쓰기로 시험하지 않는다.
3. Work #15의 ERD 시각화 검토와 UI 브랜드 보완을 마친다. 원본 자료를 임의 공개하지 않고 로고 재현을 공식 원본으로 표시하지 않는다.
4. 선행 조건을 확인한 뒤 Work #3 로그인·프로필·동의로 진행한다. U01 인증/계정, U02 필드/연령, U16 공개/보관 정책을 필요한 범위에서 결정한다.

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
| Railway | Codex 연결 도구, Claude에서는 별도 MCP/CLI 연결 필요 여부 확인 | 로컬 railway CLI 없음, Claude 접근 미검증. 설정값·비밀값을 인계 문서에 저장하지 않음 |
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
