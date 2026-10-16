# 로그인·프로필·동의 구현 계약

위치: 참가 신청·이용권·결제 → 로그인·프로필·동의 (Work #3). 기준은 PRD ACC-01~05, [ADR-0008](../adr/0008-demo-accounts-and-private-profile.md), 기존 ERD/UI/보안 설계다. 2026-10-16 사용자 결정과 구현자가 선택하는 기술 계약을 구분한다. 실제 PostgreSQL의 HTTP API와 핵심 브라우저 흐름이라는 기존 합의 경계에서 검증한다.

## 승인 범위

사전 발급한 합성 계정만 로그인한다. 공개 가입·SMS/OAuth·비밀번호 복구는 이번 Work에 추가하지 않는다. Instagram은 필수 입력이지만 다른 참가자에게 비공개다. 표시명·연령대·직업·MBTI·관심사만 동일 테이블 소개에 허용한다. 현재 Work에는 확정 테이블이 없으므로 타 참가자 프로필 공개 API를 만들지 않는다. 실제 개인정보 수집·삭제 날짜·신고/거래 보존 정책을 완성했다고 표시하지 않는다.

## 인증 기술 계약

현재 sync SQLAlchemy·psycopg를 유지한다. 비밀번호는 `pwdlib[argon2]`의 검증된 해시 API, 세션은 보안 난수의 불투명 ID와 PostgreSQL 원문 아닌 digest 저장, CSRF는 `itsdangerous`의 만료 서명 토큰을 nonce 쿠키 및 현재 세션에 바인딩하는 방식으로 구성한다. 직접 암호 알고리즘이나 JWT/refresh 체계를 만들지 않는다. 검증된 라이브러리가 세션·CSRF·권한 전체를 자동 완성한다고 주장하지 않는다.

- 공개 데이터 `User = {id: UUID 문자열, login_id: 문자열, role: participant | operator}`. API 요청으로 role·id·active·암호 hash를 지정하지 못한다.
- 인증 모듈은 `Principal(id, login_id, role)`와 FastAPI 의존성 `require_user(request) -> Principal`, `require_operator(request) -> Principal`, `require_csrf(request)`를 제공한다. 프로필 구현은 이 동일한 판정을 사용한다. 실제 함수 시그니처 변경이 필요하면 이 계약과 소비자를 함께 맞춘다.
- 절대 세션 만료 기본 12시간, 로그아웃 때 서버 철회. `AUTH_SESSION_TTL_SECONDS`는 테스트/환경 설정으로 조절하며 만료는 실제 HTTP 행동으로 검증한다.
- 배포는 HttpOnly·Secure·SameSite=Lax·Path=/·Domain 없는 `__Host-` 세션/CSRF 쿠키를 사용한다. HTTP 로컬/테스트만 별도 개발 쿠키 이름을 사용한다. `APP_ENV=production` 또는 Railway production 환경에서는 HTTP/비밀 설정 누락을 fail-closed로 처리한다. 준비 상태/heartbeat만 있는 기존 복원 DB에서도 앱이 시작되게 하며 인증 설정 누락은 인증 경계에서 안전하게 실패한다.
- `APP_ORIGIN`을 동일 출처의 정확한 URL로 설정한다. 상태 변경(login/logout 포함)에 일치하는 Origin과 유효한 `X-CSRF-Token`을 요구한다. 타 세션/변조/누락/외부 출처·null 출처는 403. 로그인 후 세션·CSRF 상태 교체, 다중 탭에 불필요한 nonce 회전 없음.
- signing key는 `AUTH_SIGNING_KEY` 런타임 환경 변수다. 개발·CI에는 명시한 합성 값, 배포에는 별도 생성 키를 쓴다. 비밀을 프론트/로그/URL에 넣지 않는다.
- 로그인 실패는 존재/미존재 동일 401. 기본 계정별 실패 5회/5분 후 임시 429와 DB 기반 재시작 지속성을 검증한다. 임의 X-Forwarded-For를 신뢰하지 않고 고비용 해시는 sync route/제한된 실행 경계에서 처리한다.
- 모든 민감 API 응답은 `Cache-Control: no-store`. 오류는 FastAPI 형식 `{detail: 고정 코드}`, 유효성 검증은 422로 구분하고 DB 장애는 비밀 없는 503으로 처리한다.

| API | 입력/결과 |
|---|---|
| GET /api/auth/csrf | `{csrf_token}`와 nonce 쿠키. 로그인 전 사용 가능 |
| POST /api/auth/login | `{login_id,password}` → `{user: User}`, 새 세션 쿠키 |
| GET /api/auth/me | `{user: User}` 또는 401 |
| POST /api/auth/logout | CSRF 검증 후 철회·쿠키 삭제, `{status:"logged_out"}` |
| GET /api/admin/session | 운영자만 `{user: User}`, 참가자 403 |

## 프로필·동의 계약

| API | 입력/결과 |
|---|---|
| GET /api/profile/options | 아래 필드의 선택지와 한국어 label. 비개인 정보 metadata만 제공 |
| GET /api/me/profile | `{profile: Profile|null, complete: boolean, missing_fields: string[]}` |
| PUT /api/me/profile | 수정 가능한 프로필 전체 draft → 같은 응답. 허용 외 필드 422, 본인 세션 소유만 저장 |
| GET /api/consent/policies | `{policies:[{purpose,version,title,body,required}]}`. 목적은 `privacy`, `operation`, 버전은 `demo-2026-10-16` |
| GET /api/me/consents | `{consents:[{purpose,version,accepted,recorded_at}],complete:boolean}` |
| PUT /api/me/consents | `{consents:[{purpose,version,accepted}]}` → 같은 현재 상태. 서버가 시각·소유자를 정하며 목적별 true/false·버전 변경 이력을 보존 |
| GET /api/admin/participants | 운영자만 `{participants:[{id,login_id,display_name,profile_complete}]}` |
| GET /api/admin/participants/{id} | 운영자만 합성 참가자의 본인 프로필/동의와 동일한 필드 계약. 암호/세션 데이터 제외 |

`Profile` 필드:

- `name`, `display_name`, `contact`, `instagram_id`, `birth_year`, `gender`, `occupation`.
- `mbtis: string[]`는 표준 16유형 복수 선택. ‘모름’은 빈 목록으로 보존하며 단일 문자열로 축소하지 않는다. 관심사·본인/희망 성향도 복수 선택이다.
- `interests`: `movies_drama`, `music`, `reading`, `writing`, `exercise`, `food_cafes`, `travel`, `photo_video`, `exhibitions_performances_art`, `fashion_beauty`, `self_development_study`.
- `self_traits`: `calm`, `energetic`, `deep_conversation`, `light_humor`, `listener`, `conversation_leader`.
- `desired_traits`: `similar`, `different`, `deep_conversation`, `comfortable_humor`, `passionate`, `calm_stable`.
- `meal_budget_bands`: `10000_20000`, `20000_30000`, `30000_plus`를 원본 범주 선택으로 보존하며 U10의 수치 경계/무제한 해석을 이 Work에서 임의 확정하지 않는다.
- `food_restrictions`, `allergies`는 `{status: unknown|none|specified, details: string|null}`. 미응답은 unknown이며 none으로 바꾸지 않는다. specified에는 내용이 필요하고 none에는 모순된 내용을 허용하지 않는다.

Draft는 미완성 저장을 허용한다. `complete`는 기본 이름·표시명·연락처·출생연도·성별·직업·Instagram과 관심사/본인/희망 성향/가격대의 최소 1개 입력을 확인한다. MBTI 모름과 음식 unknown을 알레르기 없음/식당 적합으로 취급하지 않는다. 신청 gate와 식당 적합성은 후속 Work #4/#7에서 기존 PRD·U10에 맞춰 연결하며 이 Work에서 완료 처리하지 않는다.

출생연도는 유효한 4자리 정수이고 미래 연도를 거절한다. 생일 없이 만나이를 정확히 계산한다고 표시하지 않는다. 공개 연령대는 회차 연도-출생연도로 계산한 10세 구간으로 표시하며 실제 공개는 확정 테이블 기능에서 권한 검사 후 제공한다. 성별은 기록한 값을 보존하고 이 Work에서 새로운 매칭 Hard 조건/성비 점수를 만들지 않는다. 문자열은 길이를 제한하고 텍스트로 출력한다. Instagram은 형식만 검증하며 외부 실존 계정 조회·실제 연락 발송을 하지 않는다.

동의는 로그인 조건과 구분한다. UI에서 목적별 전문·버전을 보고 직접 선택하며 서버가 accepted_at/주체를 기록한다. 미동의/구버전은 complete=false. 데모 고지는 합성 정보 범위·목적·공개 원칙을 설명하며 정식 출시의 법률 검토된 개인정보 처리방침이라고 표시하지 않는다. 정책은 두 목적별 이력과 현재 상태를 조회 가능하게 하고 같은 요청 재전송은 불필요한 중복 기록을 만들지 않는다.

## 구현 소유권과 선행

- 인증 에이전트: auth 모듈·migration `0002_auth`(down `0001`)·User/AuthSession/로그인 제한·CLI seed·pyproject/lock·auth 테스트·main.py 인증 연결 및 CSR 허용 경로 추가.
- UI 에이전트: frontend 전용(선택지 API를 사용해 canonical 값 유지), 로그인/프로필/동의·운영자 화면·실제 브라우저 검증. backend/main.py 수정 금지.
- 프로필 에이전트: auth의 Principal/의존성과 `0002_auth`가 준비되어 통합된 뒤 시작. 프로필/동의 모듈·migration `0003_profile`(down `0002_auth`)·본인/운영자 HTTP 검증·main.py 해당 라우터 연결.
- 공통 계약/ADR/HANDOFF/Issue·PR 기록은 부모만 갱신한다. UI는 API 준비 전 화면만의 tracer bullet로 시작하고 실제 API 연결 E2E를 별도로 완료한다. 구현 에이전트는 각자 TDD, 실제 PostgreSQL과 HTTP/브라우저의 합의 경계에서 검증한다.
