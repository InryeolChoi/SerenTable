# PostgreSQL 백업·격리 복원

**위치:** 개발·배포 기반 확보 → 첫 배포·CI·DB 연결 → 배포 안전장치·원격 작업 검증 (#16). 기존 PR #20의 남은 운영 검증을 잇는다.

## 전제와 범위

2026-10-16 Railway 조회에서 실제 Postgres 서비스 이미지는 `postgres-ssl:18`이었다. 로컬 Compose와 기존 CI 통합 테스트는 PostgreSQL 17을 사용하므로 같은 버전이라고 기록하지 않는다. 운영 DB를 다운그레이드하지 않고, 백업 클라이언트는 서버 내부의 pg_dump, 복원 대상은 별도 PostgreSQL 18로 맞춘다. 앱 기반 기능의 18 호환성은 아래 복원 검증 범위에서 확인한다.

현재 업무 DB에는 기반 heartbeat만 있다. 이 절차의 성공은 로그인·신청·결제 데이터의 복구 검증이나 고가용성/PITR 보장이 아니다. 이후 업무 테이블을 추가할 때 복원 후 데이터·제약 검증을 함께 확장한다.

## 1. 로컬 복구 경로 검증

Docker Desktop을 실행하고 저장소 루트에서 수행한다. 호스트 Python 3.9 이상과 Git을 사용하며 호스트 pg_dump 설치는 필요 없다. 앱 이미지는 현재 검증할 커밋에서 먼저 빌드한다.

```sh
docker build -t serentable-foundation:local .
python3 scripts/verify_postgres_recovery.py
```

이 명령은 독립 PostgreSQL 18 원본에 Alembic·worker를 실행한 뒤 백업하고, 새 로컬 컨테이너에 복원하여 HTTP readiness·worker-health를 확인한다. 초기화 중 임시 서버를 준비 완료로 오인하는 회귀 상황·원본 데이터 보존·기존 백업/임시 파일 덮어쓰기 방지·손상 파일 거부·공개 자산 경로 거부도 확인한다. 임시 DB와 앱 컨테이너는 종료 시 이 실행에서 만든 것만 정리하며 기존 DB/volume을 대상으로 삼지 않는다. CI는 런타임 이미지 빌드 후 같은 명령을 실행한다.

## 2. 실제 Railway 데이터 백업

이 경로는 별도 CLI 로그인과 Railway SSH 키·서버 신뢰 설정이 필요하다. Codex 연결 앱의 OAuth는 변수 이름만 반환하며 DB 비밀값을 꺼내 쓰지 않는다. CLI 버전은 5.69.0으로 고정한다.

```sh
npm exec --yes --package=@railway/cli@5.69.0 -- railway login
```

CLI 로그인은 사용자가 브라우저에서 수행한다. SSH 키 등록은 `railway ssh keys add --key 공개키경로 --name 설명`을 사용한다. 이번 호스트는 `~/.ssh/serentable_railway_recovery_20261016` 전용 클라이언트 키를 사용한다. 개인키는 호스트의 개인 SSH 디렉터리에서만 보관하며 저장소나 대화에 넣지 않는다. 최초 SSH 서버 신뢰는 별도 확인 사항이다. 호스트 확인을 끄거나 지문 불일치 항목을 자동 삭제하지 않는다.

프로젝트·production·Postgres ID는 스크립트에 고정되어 있다. 다른 환경에서 재사용할 때 대상부터 확인한다. 연결은 Railway SSH이며 DB TCP proxy를 생성하지 않는다. 서버의 PGUSER·PGDATABASE·PGPASSWORD를 그대로 사용하는 pg_dump는 읽기 전용 내보내기다.

```sh
python3 scripts/postgres_recovery.py backup \
  --identity-file ~/.ssh/serentable_railway_recovery_20261016 \
  --output .local-backups/railway-YYYYMMDD-HHMM.dump
```

출력은 저장소의 `.local-backups/` 아래에만 허용한다. 심볼릭 링크를 해석한 경로로 확인하며 공개 자산 경로에는 저장하지 않는다. 백업은 0600, 새 전용 디렉터리는 0700으로 생성하고 Git 제외 여부도 확인한다. 기존 파일을 덮어쓰지 않고, 임시 파일 내보내기·archive 검사 성공 후 최종 이름을 만든다. 실패한 출력은 성공한 백업으로 남기지 않는다. 비밀값이 섞일 수 있는 원시 외부 명령 오류는 공개 출력에서 숨긴다.

SSH 신뢰 확인을 완료할 수 없으면 Railway 로그인된 Dashboard의 Postgres Console·Files에서 백업 파일을 만드는 대안을 검토한다. 이 경우에도 실제 파일 다운로드와 아래 복원 검증을 마치기 전 완료로 기록하지 않는다. 이번 실행은 사용자가 명시 승인한 지문 등록 후 SSH 경로로 실제 백업·격리 복원을 완료했다. 상세 증거는 [Task 검증 기록](deployment-safety-verification.md)을 따른다. 임의 공개 DB 주소 생성은 대체 절차에 포함하지 않는다.

## 3. 받은 백업의 실제 복원 검증

```sh
python3 scripts/postgres_recovery.py restore \
  --dump .local-backups/railway-YYYYMMDD-HHMM.dump \
  --app-image serentable-foundation:local
```

복원 대상 URL을 입력받지 않는다. 명령이 만든 새 이름의 PostgreSQL 18 컨테이너만 대상으로 사용하고 포트·기존 volume을 연결하지 않는다. 단일 트랜잭션 pg_restore 완료 후 복원된 heartbeat 행 수를 확인하고, 복원 환경의 worker를 한 번 실행해 API readiness·worker-health를 HTTP로 검사한다. SHA-256, 복원 전 행 수, 결과를 기록하되 개별 행·비밀번호·DB URL은 출력하지 않는다. heartbeat가 오래되어 worker-health가 실패하는 것을 방지하기 위해 새 환경에서만 heartbeat를 갱신한다.

백업은 이 호스트의 수동 논리 사본이다. 호스트 디스크 손실과 같은 장애까지 복구할 수 있는 별도 저장소·자동 일정·암호화 백업은 아직 구성하지 않았다. 개발 종료 및 데이터/스키마 변경 전 백업→복원 검증을 실행하는 운영 경로로 사용하며, 다른 머신에서 이어갈 때 dump 자체가 Git에 따라오지 않는다는 점을 확인한다.

## 비용 설정과 확인

사용자 승인: Compute 월 $10 이메일 알림 / $20 중단. workspace 전체 기준이며 이 프로젝트만의 비용 상한이 아니다. Agent 한도는 별개다. 한도 도달 시 앱이 중단되므로 심사 접근 기간에도 실제 사용량을 점검한다. 아래 조회는 읽기 전용이다.

```sh
npm exec --yes --package=@railway/cli@5.69.0 -- railway usage \
  --workspace 32735683-9397-4e69-bf00-f0ff3c1eb121 --json
npm exec --yes --package=@railway/cli@5.69.0 -- railway usage limit status \
  --target workspace --workspace 32735683-9397-4e69-bf00-f0ff3c1eb121 --json
```

[Railway 비용 제어](https://docs.railway.com/pricing/cost-control), [Railway SSH](https://docs.railway.com/cli/ssh), [PostgreSQL pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html), [pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html).
