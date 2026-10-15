# 첫 배포·CI·DB 연결 실행 지침

대상: 개발·배포 기반 확보 → 첫 배포·CI·DB 연결, Issue #2. 기반 구현은 인증·매칭·업무 처리를 완성하지 않는다. 참가자/어드민 경로는 공개 준비 화면이며 관리 데이터가 없다. 실제 Railway 자원과 모바일 기기 검증은 별도 완료 증거가 필요하다.

## 런타임과 의존성

구현은 Python 3.12, Node 22 LTS, PostgreSQL 17, uv 0.13.1을 기준으로 한다. ORM은 SQLAlchemy와 psycopg, 마이그레이션은 Alembic이다. Python 의존성은 `uv.lock`, 화면은 `frontend/package-lock.json`을 고정한다. 로컬·CI·Docker에서 같은 minor와 lock을 사용한다. 초기 로컬 화면 빌드는 호스트 Node26에서도 확인했으며 실제 Node22 빌드는 Docker에서 확인한다.

uv 설치와 Node22, Docker Desktop 실행 후 저장소 루트에서 실행한다.

```sh
docker compose up --build -d
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/readiness
curl --fail http://127.0.0.1:8000/api/worker-health
docker compose logs app worker
```

화면은 `/`, `/participant`, `/admin`에 있다. Docker의 Node 단계가 화면을 빌드하고 Python 이미지에 포함한다. API와 작업 실행기는 같은 이미지다. 로컬 DB와 포트는 외부 공개하지 않는다. `compose.yaml`의 비밀번호는 로컬 전용 예제이며 호스팅 DB에 재사용하지 않는다. `docker compose down`은 볼륨을 보존한다. `down -v`는 데이터를 삭제하므로 기본 정리 명령으로 쓰지 않는다.

코드 수정 후 로컬 프로세스로 검증하려면 `uv sync --locked`, `npm ci --prefix frontend`, `npm run build --prefix frontend`을 실행한다. `.env.example`은 참조만 하며 자동으로 읽지 않는다. `DATABASE_URL`을 실제 로컬 DB에 설정하고 `uv run alembic upgrade head` 후 `uv run uvicorn serentable.main:app --app-dir backend`으로 실행한다. 준비 화면만 확인할 때 DB 없이 liveness는 200, readiness는 503이다.

## 자동 검사

CI는 모든 PR과 `main`, `integration/mvp` push에서 실행한다. PostgreSQL 서비스 컨테이너를 시작하고 화면 타입 검사/빌드, Python lint/format, Alembic upgrade, 실제 DB HTTP 통합 테스트, Chromium 모바일 크기 화면 이동/새로고침, 런타임 이미지 빌드를 필수 단계로 수행한다. 조건부 성공이나 DB 없는 skip을 사용하지 않는다.

테스트 DB는 운영 DB와 별도 인스턴스를 사용한다. 아래 명령의 `TEST_DATABASE_URL`은 같은 로컬 전용 테스트 DB다. 외부 제품 동작은 HTTP와 별도 worker 프로세스로 확인하고 DB 내부 레코드를 기대값으로 조회하지 않는다.

```sh
npm run build --prefix frontend
uv run alembic upgrade head
PYTHONPATH=backend uv run pytest -q
uv run ruff check backend tests migrations
uv run ruff format --check backend tests migrations
npm exec --prefix frontend -- playwright install chromium
npm run test:e2e --prefix frontend
```

마지막 브라우저 검사는 테스트 도구의 모바일 화면 에뮬레이션이다. 실제 모바일 기기 접속 완료를 뜻하지 않는다.

## Railway 서비스 설정

신규 서비스에서 구형 `railway.toml`/`railway.json`은 사용하지 않는다. Dashboard 기반으로 한 프로젝트의 PostgreSQL·API·worker 세 서비스를 구성한다. 사전 로그인, 플랜·결제 확인, GitHub App의 비공개 저장소 접근 승인은 사용자 계정 작업이다. 비밀값은 채팅이나 커밋에 넣지 않는다.

| 항목 | API 서비스 | worker 서비스 |
|---|---|---|
| 소스·루트 | GitHub SerenTable, 루트 `/` | 동일 |
| 빌드 | 루트 Dockerfile | 동일 |
| 배포 브랜치 | 초기 `integration/mvp`, 최종 승인 후 `main` | 동일 |
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

월 3~5만원 상한은 목표이며 아직 견적이나 지출 승인이 아니다. 실제 플랜 기본 비용과 세 서비스 RAM/CPU·볼륨·네트워크 합계를 확인하고 Railway의 사용량 알림(soft)과 중단 한도(hard)를 구분해 설정한다. hard limit 도달 시 서비스가 중단될 수 있다. 심사 기간과 결과 안내 기간의 가용성을 고려한다. 예약 실행용 worker는 절전시키지 않는다. 첫 24시간 사용량을 측정하고 예상 비용을 기록한다.

PostgreSQL volume 백업의 주기·보존·권한을 대시보드에서 설정·확인한다. 설정만 확인한 것은 복원 검증 완료가 아니다. 별도 빈 테스트 DB에 논리 백업을 복원해 확인한다. 아래는 로컬 Compose DB용 예시다. 백업 파일은 Git에 올리지 않고 접근 제한한 저장소에 둔다.

```sh
umask 077
docker compose exec -T postgres pg_dump -U serentable -d serentable -Fc > /private/tmp/serentable-backup.dump
docker compose exec -T postgres createdb -U serentable serentable_restore
docker compose exec -T postgres pg_restore -U serentable -d serentable_restore --exit-on-error < /private/tmp/serentable-backup.dump
```

복원용 앱/worker를 별도 DB에 연결해 readiness와 heartbeat를 확인한다. 기존 운영 DB를 대상으로 restore 명령을 실행하지 않는다. Railway의 volume restore는 같은 환경의 staged change와 재배포를 수반하므로 대상·복원 시점·일시 중단·되돌림을 먼저 확인한다.

## 모바일 원격 작업

모바일 Codex의 실제 실행 환경은 미확인이다. GitHub 저장소 권한, 실행 환경의 checkout/브랜치, 비밀값 전달 경로, PR/CI 확인 가능 여부를 사용자 기기에서 실제 확인한다. 이 지침이 실행 환경 연결을 대신하지 않는다. 이후 작은 문서 변경 지시 → 해당 브랜치 commit → PR → CI 결과 확인까지 실제 수행한 링크를 기록한다. 임의의 main 직접 push나 DB 비밀값 전달로 대체하지 않는다. 상세 제품 정책은 미결정 목록을 우선한다.

## 공식 근거

- [Railway Config as Code 변경](https://docs.railway.com/config-as-code)
- [GitHub autodeploys와 Wait for CI](https://docs.railway.com/deployments/github-autodeploys)
- [Railway healthcheck](https://docs.railway.com/deployments/healthchecks)
- [비용 제어](https://docs.railway.com/pricing/cost-control)
- [볼륨 백업](https://docs.railway.com/volumes/backups)
- [uv GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)
