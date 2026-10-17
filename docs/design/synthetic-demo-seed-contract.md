# 독립 합성 참가자100명 앱 시드

위치: **자동 매칭·실패 해결 → 규칙·데이터·정답 기준 → 가상데이터 변환·DB 시드 구축** (Work #5). 2026-10-17 사용자 A안 승인이 기준이다. [ADR-0010](../adr/0010-independent-demo-roster-and-interest-objective.md)과 원본 준비 [계약](./source-preparation-contract.md)은 서로 다른 경로다.

## 생성·식별 규칙

- 입력 원본을 받지 않는 `python -m serentable.seed_synthetic_roster preview|load` CLI다. `data/`·원본 준비 DB를 읽지 않는다.
- 규칙 버전 `independent-synthetic-roster-v1`, 로그인 `synthetic-demo-001`~`100`, ID는 UUIDv5로 고정한다. 기존 일반 참가자4명·운영자 계정과 별도다.
- 초기 이름·표시명은 합성 참가자임을 명시한다. 연락처는 전화번호가 아닌 `DEMO-NOT-A-PHONE-번호`, Instagram은 `synthetic_demo_번호`인 가상 문자열이다. 외부 계정 확인·연락에 사용하지 않는다.
- 출생연도1990~2005를 순환하고, MBTI16개·관심사11개 중 연속3개·두 본인 성향·한 희망 성향·예산 두 구간을 결정적으로 구성한다. 실제 분포·궁합 표·성비 목표를 의미하지 않는다. 음식 제한·알레르기는 미확인 상태를 유지한다.
- 모든 프로필은 앱의 `Profile` 스키마로 검증한다. 초기 필드는 전부 생성 값이며 원본 응답 식별자와 연결하지 않는다. 새 provenance 테이블/FK나 마이그레이션은 필요하지 않다.

## 권한·멱등·실패

- 공개 API나 자동 배포 시작 작업이 아니라 운영자가 명시 실행하는 CLI다. 기본 비밀번호는 없다. `DEMO_PARTICIPANT_PASSWORD` 12~128자와 `SYNTHETIC_DEMO_SEED_ENABLED=1`이 필요하다. stdout은 집계만 제공하고 비밀번호·DB주소·DB예외를 출력하지 않는다.
- loopback PostgreSQL, DB 이름 `serentable_demo_` 접두사만 허용한다. `APP_ENV=production`, URL query, 대상 변경이 가능한 libpq 환경 변수는 접속 전에 거부한다. 원본 준비 DB와 일반 운영 DB에 기본적으로 실행할 수 없다.
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

CLI preview/load와 실제 PostgreSQL·HTTP API를 경계로 한다. 미리보기 모듈 없음 RED→미리보기 GREEN, 적재 미구현 RED→계정/프로필 적재·조회 GREEN 순서로 확인했다. 100명 완성 프로필·로그인·동의/신청/권리 미생성·수정 보존·동시 재실행·중간 DB 오류 롤백·예약 로그인 충돌 보호·위험한 대상 접속 전 거부를 검증한다. 최종 수치·PR은 인계 기록과 PR checks를 따른다.

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
생성 후 인계 기록에 연결한다.
```
