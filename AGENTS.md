# SerenTable 작업 지침

한국어의 정리된 말투로 소통한다. 이 파일은 Codex와 Claude Code가 공유하는 프로젝트 규칙이다. 현재 상태는 복제하지 않고 아래 인계 문서에서 확인한다.

## 시작과 인계

1. 새 세션·도구 전환 시 [인계 기록](docs/agents/HANDOFF.md)과 [이슈 운영](docs/agents/issue-tracker.md)을 읽는다.
2. `git status --short --branch`, `git log -5 --oneline`으로 브랜치·미커밋 변경을 확인한다. 문서의 스냅샷과 다르면 실제 Git·PR 상태를 기준으로 차이를 알린다. 사용자 변경을 보존하고 변경 주체가 불명확한 파일은 임의로 복원·삭제·stage하지 않는다.
3. 현재 Agenda → Work → Task와 직접 선행 조건을 확인하고 요청받은 범위부터 진행한다. Work/Task 추가가 필요하면 이유·위치·완료 기준·일정 영향을 먼저 설명한다.
4. 작업 종료·도구 전환 전 인계 기록에 현재 Task, 변경/미커밋 파일, 브랜치·PR, 검증 명령/결과, 미완료·다음 행동을 갱신한다. 대화 전체를 복사하는 대신 결정과 증거를 남긴다.

## 요구와 결정

- 제품 작업 시 [구현 명세](docs/design/mvp-implementation-spec.md)의 해당 요구·U 미결정 항목, [용어집](GLOSSARY.md), 관련 `docs/adr/`를 읽는다. 공식 PRD를 기준으로 하며 킥오프/폼 충돌은 [출처 대조](docs/design/requirements-source-comparison.md)에서 확인한다.
- 스택은 React·TypeScript·Vite CSR + FastAPI·별도 worker + PostgreSQL, Railway 한 프로젝트다. 사업 정책·범위 변경은 기술 구현 선택과 구분한다. 미결정 정책을 승인된 사실로 만들지 않는다.
- 데이터·상태 설계는 `docs/design/core-data-model.md`, UI는 `docs/design/ui-flow-design.md`와 `ui-brand-review.md`, 권한은 `security-verification-plan.md`를 해당 Task 브랜치에서 확인한다. 문서가 현재 브랜치에 없으면 관련 PR을 확인하고 사라진 결정을 임의로 재작성하지 않는다.

## 작업·검증·기록

- GitHub Work/Task/PR 연결은 이슈 운영 문서를 따른다. 현재 Task #16~#19의 별도 Issue·PR은 사용자 승인된 예외다. 부분 완료 PR로 부모 Work를 자동 종료하지 않는다.
- 검증은 실제 PostgreSQL을 사용하는 API·별도 실행기의 외부 행동과 핵심 브라우저 E2E를 주 경계로 한다. 매칭 작은 데이터는 독립 정답과 비교한다. 설계/문서 검토·시뮬레이션을 제품 시험 통과로 표시하지 않는다.
- 실행·테스트·배포는 [운영 지침](docs/operations/foundation-runbook.md)의 현재 명령/전제를 확인한다. 통과 결과·환경·커밋과 미검증을 구분한다.
- Task 결과마다 Blaybus 위치·복사 가능한 수행/검증 문구·실제 PR 링크·상태를 사용자에게 제공한다. Blaybus는 사용자 수동 갱신이며 실제 투입 시간을 추정하지 않는다.
- 구현/검증을 분담하거나 병렬 실행할 때 같은 checkout·브랜치를 동시에 수정하지 않는다. 별도 브랜치/작업 트리와 고정 검토 기준을 사용한다.

## 원본과 도구

- `data/` 원본과 `docs/*.pdf`는 로컬에서 보존한다. 원본·개별 응답·비밀값을 Git·정적 자산·로그·공개 PR에 올리지 않는다. 공유 시드의 생성/식별 규칙은 별도 승인 사항이다.
- 도구 접근은 세션마다 확인한다. 다른 도구의 MCP·로그인·승인·모바일 연결을 자동 상속했다고 가정하지 않는다. 비밀값 대신 설정 위치와 확인 결과만 기록한다.
- 스킬을 사용할 때 실제 `SKILL.md`를 읽는다. 공통 로컬 위치 `~/.agents/skills/`와 도구별 설치를 확인하며 명령 이름이 같다는 이유로 등록·동작이 같다고 가정하지 않는다. 별도 스킬 도구가 없으면 파일 지침을 읽어 적용 가능한 절차를 따른다.
