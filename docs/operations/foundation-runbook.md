# 첫 배포·CI·DB 연결 실행 지침

대상: 개발·배포 기반 확보 → 첫 배포·CI·DB 연결, Issue #2. 기반 구현은 인증·매칭·업무 처리를 완성하지 않는다. 참가자/어드민 경로는 공개 준비 화면이며 관리 데이터가 없다. 현재 공개 URL은 https://chanceplate.up.railway.app 이다. 실제 배포·모바일 확인 결과와 남은 운영 검증은 [실행 기록](../design/implementation-progress.md)에 구분한다.

## 런타임과 의존성

구현은 Python 3.12, Node 22 LTS, PostgreSQL 17, uv 0.13.1을 기준으로 한다. ORM은 SQLAlchemy와 psycopg, 마이그레이션은 Alembic이다. Python 의존성은 `uv.lock`, 화면은 `frontend/package-lock.json`을 고정한다. 로컬·CI·Docker에서 같은 minor와 lock을 사용한다. 초기 로컬 화면 빌드는 호스트 Node26에서도 확인했으며 실제 Node22 빌드는 Docker에서 확인한다.

## Docker로 앱 동작 확인

Docker Desktop만 실행한 뒤 저장소 루트에서 실행한다. Node·Python·uv는 이미지 안에서 설치되므로 호스트에 설치할 필요가 없다. 이 경로는 컨테이너 앱의 동작 확인이며 호스트 자동 테스트 실행과 구분한다.

```sh
docker compose up --build -d
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/readiness
curl --fail http://127.0.0.1:8000/api/worker-health
docker compose logs app worker
```

화면은 `/`, `/participant`, `/admin`에 있다. Docker의 Node 단계가 화면을 빌드하고 Python 이미지에 포함한다. API와 작업 실행기는 같은 이미지다. 로컬 DB와 포트는 외부 공개하지 않는다. `compose.yaml`의 비밀번호는 로컬 전용 예제이며 호스팅 DB에 재사용하지 않는다. `docker compose down`은 볼륨을 보존한다. `down -v`는 데이터를 삭제하므로 기본 정리 명령으로 쓰지 않는다.

## 호스트에서 자동 검사 실행

이 경로는 호스트에 Node22·uv 0.13.1과 Python 3.12가 필요하다. 아래 명령은 저장소 루트의 같은 셸에서 순서대로 실행한다. `.env`와 `.env.example`은 자동으로 읽지 않으므로 두 DB 변수를 명시적으로 export해야 한다. **테스트에는 운영 DB나 일반 개발 DB를 지정하지 않는다.** 별도 PostgreSQL 인스턴스를 테스트 전용으로 사용한다.

### 1. 별도 테스트 DB 준비

로컬 `127.0.0.1:55432`에만 공개한 테스트 전용 컨테이너를 생성한다. Compose의 앱 DB와 별개이다. 다음 비밀번호는 로컬 테스트 예제이며 호스팅에 재사용하지 않는다.

```sh
docker run --name serentable-foundation-pg \
  -e POSTGRES_USER=serentable \
  -e POSTGRES_PASSWORD=localtest \
  -e POSTGRES_DB=serentable_test \
  -p 127.0.0.1:55432:5432 \
  -d postgres:17-alpine
```

이미 같은 이름의 테스트 전용 컨테이너가 있으면 생성 명령을 반복하지 않는다. `docker ps -a`에서 대상과 포트·DB 용도를 확인하고, 중지되어 있으면 `docker start serentable-foundation-pg`로 시작한다. 다른 DB가 55432를 사용하면 임의로 종료하지 말고 새 로컬 포트와 아래 두 URL을 함께 바꾼다. DB 준비를 최대 30초 기다리고 실패하면 검사를 시작하지 않는다.

```sh
(
  for attempt in $(seq 1 30)
  do
    if docker exec serentable-foundation-pg pg_isready -U serentable -d serentable_test
    then
      exit 0
    fi
    sleep 1
  done
  exit 1
)
```

### 2. 같은 테스트 DB를 앱과 테스트에 지정

```sh
export DATABASE_URL='postgresql://serentable:localtest@127.0.0.1:55432/serentable_test'
export TEST_DATABASE_URL="$DATABASE_URL"
export PYTHONPATH=backend
uv sync --locked
npm ci --prefix frontend
npm run build --prefix frontend
uv run alembic upgrade head
uv run pytest -q
uv run ruff check backend tests migrations
uv run ruff format --check backend tests migrations
```

`DATABASE_URL`은 마이그레이션과 앱/worker가, `TEST_DATABASE_URL`은 통합 테스트가 사용한다. 서로 다른 DB로 지정하면 마이그레이션과 검증 대상이 달라지므로 같은 테스트 전용 URL로 설정한다. 외부 동작은 HTTP와 별도 worker 프로세스로 확인하고 DB 내부 레코드를 기대값으로 조회하지 않는다.

### 3. 브라우저 검사와 8000 포트 충돌

Playwright는 테스트용 API를 `127.0.0.1:8000`에 직접 시작한다. Compose 앱이나 수동 Uvicorn이 이미 이 포트를 사용하면 기존 서버를 재사용하지 않고 실패하도록 구성되어 있다. 다른 검증이나 복원 작업이 진행 중이면 중단하지 말고 브라우저 검사를 나중에 실행한다. Compose 앱을 멈춰도 되는 시점에만 같은 Compose 프로젝트의 `docker compose stop app`으로 앱 하나를 중지한다. 별도 프로젝트 이름을 사용했다면 `docker compose -p 해당이름 stop app`으로 대상을 명시한다. DB·worker와 볼륨은 종료·삭제하지 않는다. 수동 Uvicorn은 해당 터미널에서 종료한다.

8000이 비어 있고 앞 단계와 같은 DB 환경변수가 설정된 셸에서 실행한다.

```sh
npm exec --prefix frontend -- playwright install chromium
npm run test:e2e --prefix frontend
```

검사 후 Compose 앱을 다시 사용할 경우 중지한 동일 프로젝트에서 `docker compose start app`을 실행한다. 마지막 브라우저 검사는 모바일 화면 에뮬레이션이며 실제 모바일 기기 접속 완료를 뜻하지 않는다. 준비 화면만 별도로 확인하려면 `uv run uvicorn serentable.main:app --app-dir backend`을 사용한다. DB 변수 없이 실행한 경우 liveness는 200, readiness는 503이다.

## CI 자동 검사

CI는 모든 PR과 `main`, `integration/mvp` push에서 실행한다. 별도 PostgreSQL 서비스 컨테이너와 두 DB 변수를 워크플로에서 설정하고 화면 타입 검사/빌드, Python lint/format, Alembic upgrade, 실제 DB HTTP 통합 테스트, Chromium 모바일 크기 화면 이동/새로고침, 런타임 이미지 빌드를 필수 단계로 수행한다. 조건부 성공이나 DB 없는 skip을 사용하지 않는다.

## Railway 서비스 설정

신규 서비스에서 구형 `railway.toml`/`railway.json`은 사용하지 않는다. Dashboard 기반으로 한 프로젝트의 PostgreSQL·API·worker 세 서비스를 구성한다. 사전 로그인, 플랜·결제 확인, GitHub App의 비공개 저장소 접근 승인은 사용자 계정 작업이다. 비밀값은 채팅이나 커밋에 넣지 않는다.

| 항목 | API 서비스 | worker 서비스 |
|---|---|---|
| 소스·루트 | GitHub SerenTable, 루트 `/` | 동일 |
| 빌드 | 루트 Dockerfile | 동일 |
| 배포 브랜치 | `main` (PR #12 병합 후 적용) | 동일 |
| Wait for CI | 켜기 | 켜기 |
| 시작 명령 | `python -m serentable.server` | `python -m serentable.worker` |
| pre-deploy 명령 | `alembic upgrade head` | 없음 |
| DB 변수 | PostgreSQL의 private DATABASE_URL 참조 | 동일 |
| Healthcheck | `/api/readiness` | 웹 healthcheck 없음 |
| 공개 도메인 | API에만 생성 | 생성하지 않음 |

API가 마이그레이션을 소유한다. 첫 배포는 API pre-deploy 성공 후 worker를 시작한다. 동시에 처음 배포하면 worker는 schema가 생길 때까지 비밀값 없는 오류 로그를 기록하고 10초 간격으로 복구한다. 마이그레이션은 앱 시작 때 API/worker가 동시에 실행하지 않는다. 이후 파괴적 schema 변경은 새·이전 버전 공존과 복구 방법을 검토한 뒤 배포한다.

`PORT`는 Railway 제공 값을 읽으며 기본값은 8000이다. `PYTHONPATH`는 이미지에 포함된다. 버전은 `APP_VERSION`, 없으면 `RAILWAY_GIT_COMMIT_SHA`, 둘 다 없으면 development를 반환한다. 커밋 SHA를 실제 배포와 대조한다. worker는 기반 heartbeat만 실행하며 예약 매칭·발송·잠금·재시도 엔진은 아직 구현하지 않았다.

Wait for CI는 실제 서비스별 설정이다. YAML 파일만으로 활성화되지 않는다. 실패한 CI가 배포를 막는지 실제 배포 내역을 확인해야 한다. 필수 검사를 조건부 skip/neutral 처리하거나 취소 상태를 성공으로 해석하지 않는다. 배포 브랜치를 바꾸면 CI push 트리거도 함께 검토한다. PR 검증만으로 배포 브랜치 CI를 대체하지 않는다. 통합 PR 완료 전 `main` 자동 병합은 하지 않는다.

## 배포 완료 증거

1. Railway 배포 ID·commit·terminal status 기록. 빌드 로그 완료만으로 실행 성공이라 하지 않는다.
2. 공개 URL의 health 버전이 새 커밋인지, readiness가 200인지 확인한다.
3. worker 로그의 `worker_heartbeat_ok`와 worker-health 200을 별도로 확인한다. 30초간 heartbeat가 없거나 DB 조회가 실패하면 worker-health는 503이다. API readiness는 worker 생존을 보장하지 않는다.
4. 참가자/어드민 경로를 모바일 브라우저에서 열고 새로고침한다. 현재는 기능 준비 화면임을 확인한다.
5. 잘못된 DB 주소에서는 readiness 503, liveness 200이며 주소·사용자·비밀번호·드라이버 예외가 공개 응답에 없는지 확인한다.
6. 배포 시작 healthcheck는 지속 모니터링이 아니다. 실제 운영 시 별도 주기 점검과 알림을 설정하고 증거를 남긴다.

## 비용과 백업·복원

2026-10-16 실제 화면 확인: 현재 Hobby 계정의 Postgres Backups는 신규·예약 백업/PITR 생성에 Pro 업그레이드를 요구하며 백업이 없다. 아래 volume 예약 백업 설명은 이용 가능한 플랜에서의 경로다. 현 계정에서 활성화됐다고 간주하지 않는다. Hobby 유지·논리 백업 경로는 [실행·격리 복원 지침](postgres-recovery.md)으로 준비했다. 실제 Railway 데이터 검증 상태는 최신 Task 기록에서 확인한다. [최신 Task 검증 기록](./deployment-safety-verification.md)에 플랜·사용량·미완료 조건을 기록한다.

월 3~5만원은 예산 목표다. 2026-10-16 사용자가 승인한 Compute 월 $10 알림·$20 중단 한도를 설정하고 재조회로 확인했다. 원화 예산과 정확히 같은 금액이라고 보장하지 않는다. 실제 플랜 기본 비용과 세 서비스 RAM/CPU·볼륨·네트워크 합계를 확인하고 Railway의 사용량 알림(soft)과 중단 한도(hard)를 구분해 설정한다. hard limit 도달 시 서비스가 중단될 수 있다. 심사 기간과 결과 안내 기간의 가용성을 고려한다. 예약 실행용 worker는 절전시키지 않는다. 첫 24시간 사용량을 측정하고 예상 비용을 기록한다.

PostgreSQL volume 백업의 주기·보존·권한을 대시보드에서 설정·확인한다. 설정만 확인한 것은 복원 검증 완료가 아니다. 별도 빈 테스트 DB에 논리 백업을 복원해 확인한다. 아래는 로컬 Compose DB용 예시다. 백업 파일은 Git에 올리지 않고 접근 제한한 저장소에 둔다.

```sh
umask 077
docker compose exec -T postgres pg_dump -U serentable -d serentable -Fc > /private/tmp/serentable-backup.dump
docker compose exec -T postgres createdb -U serentable serentable_restore
docker compose exec -T postgres pg_restore -U serentable -d serentable_restore --exit-on-error < /private/tmp/serentable-backup.dump
```

복원용 앱/worker를 별도 DB에 연결해 readiness와 heartbeat를 확인한다. 기존 운영 DB를 대상으로 restore 명령을 실행하지 않는다. Railway의 volume restore는 같은 환경의 staged change와 재배포를 수반하므로 대상·복원 시점·일시 중단·되돌림을 먼저 확인한다.

## 모바일 원격 작업

2026-10-16 사용자 휴대폰 원격 접속 가능 보고와 `REMOTE-20261016` 지시를 받아 문서 commit → PR #20 → 실제 CI 성공을 확인했다([증거](./deployment-safety-verification.md)). 기기 모델·OS를 직접 확인한 것은 아니다. GitHub 저장소 권한, checkout/브랜치와 호스트의 비밀값 전달 경로를 유지하고 원격 지시를 main 직접 push나 대화의 DB 비밀값 전달로 대체하지 않는다. 호스트의 절전·네트워크·앱 종료는 원격 가용성에 영향을 준다. 상세 제품 정책은 미결정 목록을 우선한다.

## 공식 근거

- [Railway Config as Code 변경](https://docs.railway.com/config-as-code)
- [GitHub autodeploys와 Wait for CI](https://docs.railway.com/deployments/github-autodeploys)
- [Railway healthcheck](https://docs.railway.com/deployments/healthchecks)
- [비용 제어](https://docs.railway.com/pricing/cost-control)
- [볼륨 백업](https://docs.railway.com/volumes/backups)
- [uv GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)


## 현재 검증과 다음 Task

2026-10-15 사용자 Blaybus 상태: 첫 화면 모바일 검증 / Railway 배포 / DB 연결과 CI 구성 / 최소 React·FastAPI 앱 구성 완료. 새 Task `배포 안전장치·원격 작업 검증`은 진행 중이며 기존 인수 기준을 이어받는다.

초기 조회에서 꺼져 있던 API·worker의 `source.checkSuites`를 true로 활성화했다. 임시 검증 브랜치의 실패 CI는 두 배포 모두 SKIPPED, 정상 복구 CI는 두 배포 모두 SUCCESS였다. 두 서비스의 main 복구와 공개 상태 응답을 확인했다([실제 기록](./ci-gate-verification.md)). 후속 검증에서 모바일 지시→PR→CI 성공, API readiness 배포 healthcheck 보완, Hobby 플랜 백업 제약을 확인했다. Compute 비용 한도는 후속 검증에서 설정했다. 실제 Railway 데이터 백업·복원 상태는 최신 기록을 따른다([최신 Task 기록](./deployment-safety-verification.md)).

worker Pre-deploy에 상시 실행 명령을 넣으면 종료를 기다리며 배포가 멈춘다. worker의 Pre-deploy는 비워 두고 Start Command에 `python -m serentable.worker`를 넣는다. 해당 위치 오류를 수정한 뒤 배포 `8cc2fc2a-b9a7-4026-9c66-11a1c33381c4`의 SUCCESS, 실행 replica 1개와 heartbeat를 확인했다. heartbeat 응답만으로 배포 성공을 판단하지 않는다.
