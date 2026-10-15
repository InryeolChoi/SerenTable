# SerenTable — 우연한 식탁 MVP

2026 우연한 식탁 MVP 해커톤의 소셜다이닝 서비스 프로젝트다. PRD P0와 12단계 E2E 흐름을 심사용 배포 환경에서 검증하는 것이 목표다.

## 일정과 현재 상태

- 본격 구현 시작: 2026-10-16.
- 개발 완료 목표: 2026-10-20.
- 제출 마감: 2026-10-21 23:59, Asia/Seoul.
- React·FastAPI·PostgreSQL·별도 worker 기반을 main에 병합하고 Railway에 배포했다. 사용자가 첫 화면 모바일 검증을 완료로 표시했다. 로그인·신청 등 제품 기능과 배포 안전장치·원격 작업 검증은 후속 Task다.
- 현재 배포: https://chanceplate.up.railway.app

## 확정된 방향

- React + TypeScript + Vite CSR 참가자/운영자 화면 + FastAPI 핵심 업무 서버.
- 운영 자동화 신뢰성을 주력으로 검증하고, 매칭 필수조건과 작은 데이터 정답 비교를 확보한다.
- 가상 식당 재고를 자동 배정하고 재고 부족은 운영자 예외로 처리한다. 외부 식당 예약 API는 제외한다.
- 심사용 배포 MVP. 운영비 상한은 월 3~5만원이다.
- Railway 한 프로젝트에 화면을 제공하는 FastAPI 앱과 PostgreSQL을 배포한다. 인증·채팅은 라이브러리를 활용해 앱 안에 구성한다.
- API와 작업 실행기는 같은 Python 코드베이스에서 실행을 분리한다. 매칭 실행당 100명 검증을 목표로 한다.
- 이용권은 PRD 우선의 1회권 + 모의 구독을 구현한다. 성향 점수는 명시적 대응 규칙표를 사용한다.
- 인증/채팅/작업 라이브러리·매칭 알고리즘·세부 업무 정책은 후속 결정이다.

## 문서

- [MVP 구현 명세서](docs/design/mvp-implementation-spec.md)
- [Work별 GitHub Issue·PR 발행 계획](docs/design/github-ticket-plan.md)
- [승인된 핵심 설계·UI·보안·DB 시드 배치](docs/design/design-readiness-plan.md)
- [도메인 용어](GLOSSARY.md)
- [설계 인터뷰와 결정 대기 항목](docs/design/mvp-interview.md)
- [사용자가 전달한 킥오프 기록](docs/design/kickoff-notes.md)
- [식당 배정 범위](docs/adr/0002-simulated-venue-inventory.md)
- [핵심 업무 서버의 책임](docs/adr/0003-fastapi-core-backend.md)
- [Railway 단일 플랫폼 배포](docs/adr/0004-railway-single-platform.md)
- [CSR 화면](docs/adr/0005-react-vite-csr.md)
- [별도 작업 실행기](docs/adr/0006-separate-job-runner.md)
- [실제 신청 폼 참고](docs/design/application-form-reference.md)
- [이용권 범위](docs/adr/0007-prd-ticket-scope.md)
- [Blaybus 구조·운영 기록](docs/design/blaybus-plan.md)

공식 PRD가 요구사항 기준이다. 제공받은 PDF는 로컬 `docs/`에 보관하며 Git에는 포함하지 않는다. 문서의 원본 PDF 링크는 해당 파일이 있는 로컬 환경에서 확인할 수 있다. 현장 Q&A와 PRD의 차이는 설계 인터뷰에 명시한다.

사용자가 Blaybus Workspace 등록을 완료했다. 계획·실제 진행·투입 시간은 Blaybus에 기록하고 GitHub의 설계·PR·검증 근거를 연결한다. Blaybus는 사용자가 수동 갱신하며, AI가 자동 동기화했다고 기록하지 않는다. [Work Issue 11개](https://github.com/InryeolChoi/SerenTable/issues)가 발행되었으며 선행 관계에 따라 착수한다.

작업 완료 시 사용자에게 Blaybus 수동 갱신 위치·기록 문구·상태·증거를 안내한다. Work 완료와 Agenda 변경은 실제 조건 충족 시 요청한다. 상세 형식은 [Workspace 운영 기록](docs/design/blaybus-plan.md)을 따른다.

Blaybus Work 하나를 GitHub Issue 하나에 연결한다. PR과 Task는 강제 1:1 관계를 두지 않으며, 각 Task 완료 시 관련 PR과 수행·검증 결과를 Task 작업 내용 기록란에 남긴다.

기본 진행 순서는 등록한 Agenda → Work → Task이다. Work·Task 추가가 필요하면 이유·소속·완료 기준·일정 영향을 먼저 안내한다.

## 로컬 실행과 검증

`docker compose up --build -d`로 로컬 앱·DB·작업 실행기를 시작한다. [첫 배포 실행 지침](docs/operations/foundation-runbook.md)에서 런타임·자동 검사·Railway 설정·비용·백업/복원·모바일 원격 작업의 미완료 전제를 확인한다. 현재 공개 화면은 준비 상태이며 로그인·어드민 권한·제품 기능을 제공하지 않는다.
