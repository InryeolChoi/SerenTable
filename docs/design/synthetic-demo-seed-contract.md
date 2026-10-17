# 독립 합성 참가자100명 앱 시드

**후속 B안:** 사용자가 별도 합성100명의 동의·신청·모의 결제 시연 준비를 추가 승인했다. 계정·프로필을 만드는 이 CLI의 범위는 유지하며 [별도 시나리오 CLI](./synthetic-demo-scenario-contract.md)·[PR #37](https://github.com/InryeolChoi/SerenTable/pull/37)에서 연결한다. 이 CLI 자체가 동의/거래를 만든다는 의미는 아니다.

위치: **자동 매칭·실패 해결 → 규칙·데이터·정답 기준 → 가상데이터 변환·DB 시드 구축** (Work #5). 2026-10-17 사용자 A안 승인이 기준이다. [ADR-0010](../adr/0010-independent-demo-roster-and-interest-objective.md)과 원본 준비 [계약](./source-preparation-contract.md)은 서로 다른 경로다.

## 생성·식별 규칙

- 입력 원본을 받지 않는 `python -m serentable.seed_synthetic_roster preview|preflight|load` CLI다. `data/`·원본 준비 DB를 읽지 않는다.
- 규칙 버전 `independent-synthetic-roster-v1`, 로그인 `synthetic-demo-001`~`100`, ID는 UUIDv5로 고정한다. 기존 일반 참가자4명·운영자 계정과 별도다.
- 초기 이름·표시명은 합성 참가자임을 명시한다. 연락처는 전화번호가 아닌 `DEMO-NOT-A-PHONE-번호`, Instagram은 `synthetic_demo_번호`인 가상 문자열이다. 외부 계정 확인·연락에 사용하지 않는다.
- 출생연도1990~2005를 순환하고, MBTI16개·관심사11개 중 연속3개·두 본인 성향·한 희망 성향·예산 두 구간을 결정적으로 구성한다. 실제 분포·궁합 표·성비 목표를 의미하지 않는다. 음식 제한·알레르기는 미확인 상태를 유지한다.
- 모든 프로필은 앱의 `Profile` 스키마로 검증한다. 초기 필드는 전부 생성 값이며 원본 응답 식별자와 연결하지 않는다. 새 provenance 테이블/FK나 마이그레이션은 필요하지 않다.

## 권한·멱등·실패

- 공개 API나 자동 배포 시작 작업이 아니라 운영자가 명시 실행하는 CLI다. 기본 비밀번호는 없다. `DEMO_PARTICIPANT_PASSWORD` 12~128자와 `SYNTHETIC_DEMO_SEED_ENABLED=1`이 필요하다. stdout은 집계만 제공하고 비밀번호·DB주소·DB예외를 출력하지 않는다.
- 기본 `--target local`은 loopback PostgreSQL·`serentable_demo_` 접두사만 허용하고 production을 거부한다. 추가 `--target railway`는 코드에 고정한 SerenTable 프로젝트·production 환경·API 서비스 ID가 컨테이너 환경과 모두 일치하고, private Railway 호스트·`railway` DB일 때만 허용한다. worker·타 환경·타 프로젝트는 거부한다. 두 모드 모두 URL query·대상을 바꾸는 libpq 환경 변수를 접속 전에 거부한다.
- `preflight`는 대상·암호 설정의 유효성만 확인하며 DB 접속/쓰기 없이 집계를 출력한다. Railway 환경에서도 명시 모드와 실행별 opt-in 없이는 운영 적재가 활성화되지 않는다. ID 확인은 대상 오선택 방지이며 SSH 인증을 대체하지 않는다.
- 100명 전체를 한 트랜잭션으로 처리하고 시드 전용 advisory lock으로 동시 실행을 직렬화한다. 중간 오류는 전체 롤백한다.
- 기존 로그인과 결정적 ID/역할이 일치하지 않으면 전체 중단한다. 임의 기존 계정을 채택하지 않는다. 기존 프로필·비밀번호·활성 상태·세션을 덮어쓰지 않는다.
- 동의·신청·회차·결제·권리·배치는 만들지 않는다. 참가자는 합성 계정으로 로그인하여 기존 화면/API로 동의·신청·모의 결제를 진행한다. 대량 자동 시연 시나리오는 후속 범위다.

## 실행

기존 DB를 초기화하거나 원본 준비 DB 주소를 재사용하지 않는다. 별도의 로컬 데모 DB를 생성하고 현재 마이그레이션을 적용한다. DB URL과 비밀번호는 셸 환경에서만 제공한다.

```sh
PYTHONPATH=backend uv run python -m serentable.seed_synthetic_roster preview
# 전용 로컬 데모 DATABASE_URL과 합성 계정 비밀번호를 설정한 셸
SYNTHETIC_DEMO_SEED_ENABLED=1 PYTHONPATH=backend uv run python -m serentable.seed_synthetic_roster load
```

기존 `seed_demo_accounts`는 운영자·기본 참가자4명 발급용으로 유지한다. 두 CLI를 함께 실행하면 합성 참가자100명 외에 기본 참가자4명이 존재한다. `load` 재실행으로 암호를 교체하지 않으므로 자격 증명 변경은 별도 절차다.

## 검증·남은 항목

CLI와 실제 PostgreSQL·HTTP API를 경계로 한다. 미리보기 모듈 없음 RED→미리보기 GREEN, 적재 미구현 RED→계정/프로필 적재·조회 GREEN 순서로 확인했다. 초기 로컬 전용12개 PASS(8.71초), 전체 API·오라클·두 CLI 회귀154개 PASS(210.11초), 해당 코드의 CI38993123503 SUCCESS. 이후 Railway preflight 경로 부재 RED→명시 대상 확인 GREEN, 잘못된 프로젝트/환경/worker·DB/query/libpq 우회·기본 모드 production 거부를 더해 집중 **22개 PASS**(10.92초). Ruff check/format PASS. 고정 `1b6615a...00bfe94` 독립 Standards/Spec 수정필요0건, Railway 보완과 최종 CI는 [PR #36](https://github.com/InryeolChoi/SerenTable/pull/36)에서 별도 확인한다.

실제 실행: 로컬 PG17 컨테이너 `serentable-foundation-pg`, loopback55432의 새 전용 DB `serentable_demo_hackathon_20261017`에100계정·100프로필 적재, 재실행0/0. 첫/마지막 계정의 앱 HTTP 로그인·완성 프로필·동의/신청/권리 없음도 확인했다. 이 DB는 보존하며 테스트 초기화 대상으로 사용하지 않는다. 기본 운영자/참가자4명 발급 CLI는 이 DB에 아직 실행하지 않았다. 원본 준비 DB·운영 DB에 쓰지 않았다. 자격 증명은 기록/출력하지 않는다.

## Railway 심사용 운영 DB 적재 순서

사용자가 로컬 검증 후 운영 적재 의도를 재확인했다. 현재 **대상 형식 확인만 완료, 적재는 미실행**이다. 공식 CLI SSH로 API 컨테이너의 프로젝트·환경·서비스 일치, private DB·기대 DB명·query 없음·합성 암호 설정 길이를 boolean으로 확인했다. 비밀값은 내보내지 않았다.

1. main 대상 PR #34 → #36을 사용자 검토·머지하고, B안 시연에는 후속 #37도 병합한다. API/worker 배포 버전과 readiness를 확인한다. PR #35는 독립 병합 가능하다.
2. [기존 백업 절차](../operations/postgres-recovery.md)로 새 논리 백업을 보존한다. 운영 DB에 복원하거나 초기화하지 않는다.
3. 같은 공식 Railway SSH의 프로젝트·environment·API service를 명시한 원격 명령에서 `env SYNTHETIC_DEMO_SEED_ENABLED=1 python -m serentable.seed_synthetic_roster preflight --target railway`를 실행한다. 비밀번호는 기존 컨테이너 환경에서만 사용한다.
4. 확인한 같은 컨테이너에서 명령의 `preflight`를 `load`로 바꿔1회 실행하고 집계를 기록한다. 다시 실행해 신규0/0을 확인한다. opt-in은 해당 명령 프로세스에만 적용하고 서비스 시작/Pre-deploy에는 넣지 않는다.
5. 공개 HTTPS의 운영자 목록과 합성 계정 로그인·프로필 조회로 확인한다. 기존 계정·신청·결제 보존과 동의/거래 미생성을 구분해 기록한다. 심사용 자격 증명은 공개 PR에 올리지 않고 제출 경로로 전달한다.

원본 변환의 날짜/나이 정책, 공개 배포 DB 적재·심사용 계정 전달, 대량 모의 거래·실행 시나리오와 매칭 점수 구현은 남아 있다. 따라서 Work #5와 본 Task 전체는 **진행 중**이다. 새 Work/Task는 만들지 않는다.

## Blaybus 복사 문구

```text
[수행]
- 승인한 A안에 따라 원본과 연결되지 않는 합성 참가자100명의 계정·완성 프로필을 만드는 CLI를 구현했다.
- 생성 규칙·합성 표시·결정적 ID를 문서화하고, 재실행 시 기존 프로필·비밀번호·활성 상태를 보존하도록 했다.
- 원본294응답은 기존 비공개 준비 DB에 보존하며 자동 동의·신청·결제를 만들지 않았다.

[검증]
- 실제 PostgreSQL과 HTTP API에서 100명 생성·프로필 완성·로그인을 확인했다.
- 재실행·동시 실행의 중복 방지, 수정한 입력 보존, 중간 DB 오류의 전체 롤백과 재시도를 확인했다.
- 기존 계정 충돌과 허용하지 않은 DB 대상은 안전하게 거부했다. 정확한 검사 수와 CI는 연결 PR을 따른다.

[남은 항목]
- 공개 배포 DB 적재와 심사용 계정 전달, 대량 시연 시나리오 연결.
- 원본 변환의 미정 날짜·나이 정책과 매칭 점수·제외 관계 기준.
- Task와 상위 Work는 진행 중으로 유지한다.

[PR]
https://github.com/InryeolChoi/SerenTable/pull/36
```
