# 배포 환경 12단계 정상 흐름 검증 절차

- 작성: 2026-10-19, Work #10 「12단계 E2E·100명·복구 검증」의 배포 환경 부분
- 도구: [`scripts/verify_deployed_twelve_step.py`](../../scripts/verify_deployed_twelve_step.py) (표준 라이브러리만 사용)
- 기준: [구현 명세 §4](../design/mvp-implementation-spec.md#4-prd-12단계-e2e-인수-기준), [12단계 인수 근거 매트릭스](../design/twelve-step-acceptance-matrix.md), [신청·모의 결제 배포 검증](./application-deployment-verification.md)
- 상태: **배포 환경에서는 아직 실행하지 않았다.** 아래 "로컬 실행 결과"는 로컬 근거이며 운영 통과가 아니다.

## 무엇을 하는 도구인가

배포된 API 컨테이너 안에서 공개 HTTPS 주소(`DEPLOY_ORIGIN`)로만 요청해 PRD 12단계 정상 흐름을 합성 계정(`participant-01`~`04`, `operator`)으로 재현한다. DB 직접 접근·시계 덮어쓰기·내부 ASGI 호출이 없다. 매칭·확정·식당 배정·단체방·리마인드·행사 중 콘텐츠·후기 리마인드는 운영 worker가 실제 시각에 수행하고, 스크립트는 그 결과를 참가자·운영자 API로 확인한다.

출력은 고정된 `PASS`/`FAIL`/`WAIT`/`INFO` 이름과 id·시각·API 오류 코드(`code=...`)·HTTP 상태(`status=...`)뿐이다. 응답 본문·쿠키·비밀번호는 출력하지 않으며, 그 외 값은 `<redacted>`로 바뀐다. 예외 메시지 대신 예외 종류 이름만 출력한다.

종료 코드: `0` 통과, `1` 실패, `2` 설정 거절(HTTPS 아님·비밀번호 없음·slot id 없음·시간 값 오류·공개 회차 생성 확인 없음), `3` 아직 도달할 수 없는 단계(출력된 시각 이후 같은 명령으로 재실행). 마지막 줄은 항상 단계 판정(`PASS`/`FAIL`/`WAIT <단계> <slot id>`)이다. 그 앞의 로그아웃 정리는 판정과 종료 코드를 바꾸지 않으며, 로그아웃하지 못한 계정만 `INFO logout_incomplete <계정>`으로 남긴다(세션은 만료 시간이 지나면 끝난다).

### 재시도와 중복 방지

- 네트워크 오류(연결 끊김·시간 초과) 재시도는 조회(GET)와, 서버가 같은 결과로 되돌려 주는 쓰기(고정 `request_key`의 신청·결제·방 메시지, 프로필·동의·후기 PUT, 체크인, 로그아웃)에만 한다.
- 회차 생성·검증 재고 등록·로그인은 다시 보내지 않는다. 응답만 유실된 경우 서버에는 이미 생겼을 수 있으므로, 회차는 운영자 회차 목록에서 같은 지역·시작 시각(초 단위로 맞춘 값, 지역+시작은 유일)으로 찾아 `PASS operator_create_slot_recovered`로 이어 가고, 재고는 목록에 있는지 확인한다. 찾지 못하면 `FAIL ... code=network_error`로 멈춘다. slot id는 알게 되는 즉시 `INFO slot_id`로 출력하고 이후 실패해도 마지막 줄에 함께 나온다.
- CSRF 토큰은 계정별로 한 번 받아 재사용하고, 로그인 직후(세션이 바뀜)나 서버가 `403 csrf_rejected`를 줄 때만 다시 받는다. 거절된 요청은 서버에서 아무것도 하지 않았으므로 새 토큰으로 한 번 더 보낸다.

## API가 정한 시간 제약 (코드 확인 결과)

| 제약 | 근거 코드 | 스크립트 설계 |
|---|---|---|
| 회차 생성: `starts_at < ends_at`, `closes_at ≤ matches_at ≤ starts_at`, `closes_at > 현재`. 최소 사전 기간은 **없다**. 지역+시작 시각은 유일 | `backend/serentable/events.py` `EventSlotInput`, `create_event_slot` | 마감 3분 뒤, 매칭 시각=마감, 시작은 마감 8분 뒤(+임의 초), 길이 10분이 기본값 |
| 신청·결제: 회차 마감 전만 가능, 동일 `request_key` 재전송은 같은 결과(마감 후에도) | `applications.py` `submit_application`, `payments.py` | 키를 `uuid5(slot id, 계정, 용도)`로 고정해 재실행 시 재전송이 된다 |
| 매칭: worker 10초 주기, `matches_at` 이후 회차당 1회. 결제(또는 활성 멤버십) 완료 신청만 대상 | `worker.py`, `matching.py`, `eligibility.py` | 운영자 조회 `/api/admin/match-runs`를 제한 시간 안에서 폴링 |
| 식당 배정: 회차 재고 중 정원 이상, **모든 멤버의 식비 구간**에 맞는 가격, 음식 제한·알레르기가 모두 `none`이어야 자동 배정(아니면 운영자 예외) | `gatherings.py` `allocate_venue`, `food_state` | 네 명의 공통 식비 구간에서 가격을 고르고, 공통 구간이 없거나 음식 조건이 `none`이 아니면 회차를 만들기 전에 FAIL |
| 리마인드: 확정 처리 시 시작까지 **24시간 이내**면 즉시 1회 게시(별도 24시간 대기 없음). 시작 시각 이후 대화 주제 1회, 종료 후 소급 게시 없음 | `gatherings.py` `process_table` | 시작을 마감 후 24시간 안으로 강제(`start_must_be_within_24h_of_close`) |
| 체크인: 시작 30분 전 ~ 종료 (ADR-0014 U15) | `attendance.py` `SEAT`, `check_in` | 시작 이후 체크인, 재전송은 200·같은 시각 |
| 만족도·사람별 선호: 종료 후에만(`409 feedback_not_open`), 수정 가능 | `feedback.py` `require_ended` | 종료 전 거절 확인 → 종료 후 저장·수정 |
| 후기 리마인드: 종료 **24시간 후 ~ 7일 이내**, 미응답 멤버에게 1회 | `feedback.py` `run_feedback_jobs` | `participant-04`만 후기를 남기지 않고, 하루 뒤 별도 단계에서 확인 |
| 다음 매칭 반영: 이전 성공 실행에서 같은 테이블이었던 쌍은 `new` 점수에서 감점(상호 재만남 쌍 제외) | `matching.py` `MET_SQL` | 두 번째 회차에 `--previous-slot-id`를 주면 `new`가 100 미만이고 이전 값 이하인지 확인 |

## 단계와 증명 범위

| 명령 | 걸리는 실제 시간 | 확인하는 것 (PRD 단계) |
|---|---|---|
| `prepare` | 약 1~2분 | 배포 버전(선택), 5계정 로그인·no-store, 참가자의 운영 API 403, 프로필·동의 완료, 운영자 회차·검증 재고 등록, 참가자 회차 조회, 신청·재전송, 1회권 모의 결제·재전송(활성 멤버십이 이미 덮으면 결제 생략 `INFO`), 매칭 적격, 운영자 신청 목록 (1) |
| `check-matching` | 마감 시각까지 대기 + worker 1~2주기 | worker 실행 SUCCEEDED, 네 명 같은 테이블 4~6인, 최소 점수 이상, 참가자별 CONFIRMED·이용권 USED, 식당 ASSIGNED(등록한 재고)·예약명, 단체방 멤버·확정/식당/리마인드 게시와 **이 테이블의** 알림(`table_id`로 구분, 이전 회차 알림은 세지 않음), 참가자 화면의 동료 목록이 테이블 인원 전체이며 표시명만 있음, 방 메시지 송신·재전송·동료 조회(표시명만), 비공개 키(`contact`·`instagram_id`·`birth_year`·`score`·`components`·`policy`)와 네 명의 연락처·Instagram·이름 값 비노출, 운영자 계정의 방 접근 거절, 마감 후 상태를 바꾼 운영자 조치 0건(아래 "운영자 조치 판정")·미해결 예외 0·대시보드 일치 (2, 3, 5, 6, 7, 9 일부, 12 일부) |
| `check-event` | 시작 시각까지 대기 + 종료까지 대기 + 25초 | 종료 전 후기 거절, 시작 후 대화 주제 1회, 4명 체크인·재전송, 종료 후 후기 3명 저장·수정, 종료 후 소급 게시 없음, 노쇼 후보 0·체크인 4·후기 3, 다시 마감 후 운영자 조치 0·예외 0 (9, 10, 12) |
| `check-feedback-reminder` | 종료 **24시간 후**(7일 이내) | 후기를 남기지 않은 `participant-04`에게 **이 테이블의** 후기 리마인드 1건(다른 회차 리마인드는 세지 않음) (10) |
| `run` | 기본값으로 약 25분 | `prepare` → `check-matching` → `check-event`를 이어서 실행 |
| 두 번째 `run --confirm-public-slot --previous-slot-id <첫 회차>` | 약 25분 | 다음 매칭에서 이전 만남이 `new` 점수를 낮춤 (11). **회차·결제가 한 벌 더 남는다** |

다루지 않는 것: 4단계 해제·재배치와 8단계 미매칭 대안·이동·환불(정상 흐름이 아니며 운영 데이터에 실패 상태를 만들게 되므로 로컬 시험 근거만 유지), 사람별 선호 저장(비선호는 영구 제외 관계를 남기므로 운영에서 보내지 않는다), 실기기 푸시 수신, 브라우저 화면.

## 사용자 실행 방법 (Railway API 컨테이너)

1. 배포 커밋을 확인한다. 이 스크립트가 확인하는 기능(Work7~9: 식당·방·리마인드·체크인·후기)이 운영에 반영된 뒤 실행한다. 반영 전이면 `check-matching` 이후가 FAIL한다. 알림을 테이블별로 구분하는 참가자 알림 응답의 `table_id`(이 검증 도구와 함께 추가)도 배포돼 있어야 한다. 없으면 `participant_0N_notified`가 FAIL한다.
2. 이미지에는 `scripts/`가 없다(Dockerfile은 `backend/`·`migrations/`만 복사). 한 파일짜리 표준 라이브러리 스크립트이므로 컨테이너의 `python`에 표준 입력으로 넘겨 실행한다. 컨테이너 안의 `DEMO_PARTICIPANT_PASSWORD`·`DEMO_OPERATOR_PASSWORD`·`APP_ORIGIN`이 그대로 쓰인다(비밀번호를 로컬로 복사하지 않는다).

   ```bash
   # 예시: 저장소 루트에서. 표준 입력 전달 방식은 사용 중인 railway ssh 버전에서 먼저 확인한다.
   railway ssh --service <API 서비스> -- env DEPLOY_EXPECT_VERSION=<배포 커밋 40자> \
     python - run --confirm-public-slot < scripts/verify_deployed_twelve_step.py
   ```

   표준 입력 전달이 안 되는 환경이면 이전 `verify_deployed_application.py` 실행 때와 같은 방법으로 파일을 컨테이너에 옮긴 뒤 `python verify_deployed_twelve_step.py run --confirm-public-slot`을 실행한다. 이 저장소 기록에는 그 전달 방법이 남아 있지 않으므로 사용자가 확인해야 한다.
3. 출력의 `INFO slot_id <id>`를 기록한다. 끊겼거나 `WAIT`(종료 코드 3)이면 같은 id로 해당 단계부터 다시 실행한다. 신청·결제·방 메시지·체크인은 같은 키·같은 결과로 재전송되므로 중복이 생기지 않는다.

   ```bash
   python - prepare --slot-id <id>          # 마감 전이면 남은 신청·결제를 이어서, 마감 후면 적격만 확인
   python - check-matching --slot-id <id>
   python - check-event --slot-id <id>
   python - check-feedback-reminder --slot-id <id>   # 종료 24시간 후 ~ 7일 이내
   ```

4. 선택 옵션: `--region`(기본 `hongdae`), `--close-minutes`·`--start-after-close-minutes`·`--duration-minutes`(분, 소수 허용), `--timeout-seconds`(단계별 대기 한도, 기본은 매칭 시각+10분·종료+3분·리마인드 2분), `--normalize-profiles`(아래), `--previous-slot-id`(11단계), `--confirm-public-slot`(아래).
5. **`--confirm-public-slot`**: 루프백이 아닌 주소에서 새 회차를 만드는 `prepare`·`run`은 이 옵션이 없으면 요청을 보내기 전에 `FAIL confirm_public_slot_required`(종료 코드 2)로 멈춘다. 만들어지는 회차는 실제 모집 회차라서 마감 전까지 **모든 참가자 화면에 보이고 실제 사용자·심사위원도 신청할 수 있다.** 스크립트는 이를 막지 않으며(정책을 새로 만들지 않는다) 모집 시간을 기본 3분(`--close-minutes`)으로 짧게 둔다. 실제 사용자가 없는 시간에 실행하고, 다른 사람이 신청하면 그 사람도 같은 매칭에 포함될 수 있음을 사용자가 감수한 뒤 이 옵션을 준다. `--slot-id`로 이어서 실행할 때는 새 회차를 만들지 않으므로 필요 없다.
6. `--allow-local-http`는 `http://127.0.0.1`·`localhost` 같은 루프백 주소에서만 HTTP를 허용하는 로컬 시험용이다. 그 밖의 `http://` 주소는 이 옵션이 있어도 거절한다(종료 코드 2).

### 운영자 조치 판정 (12단계)

이 회차·테이블·검증 재고와 이 회차의 예외(상태 무관) id를 대상으로 한 운영자 감사 기록 중 마감 시각 이후 것을 본다. 읽기만 하는 감사 행위(CSV 내보내기 `export`)는 개입으로 세지 않고, 그 밖의 행위(예외 해결 `exception_resolve`, 음식 조건 승인 `venue_food.approve` 등, 앞으로 추가될 행위 포함)는 모두 개입으로 세어 `FAIL no_operator_action_after_close <행위>`가 된다.

마감 뒤에 `prepare --slot-id`로 이어서 실행했는데 그 회차의 검증 재고가 없으면, 재고를 늦게 등록하지 않고 `FAIL verified_inventory_missing_after_close`로 멈춘다. 늦은 등록 자체가 마감 후 운영자 조치이고 worker의 식당 배정과 겹칠 수 있어, 그 회차로는 정상 흐름을 증명할 수 없다. 새 회차로 다시 실행한다.

### 합성 계정 프로필

기본 동작은 비어 있는 필수 항목과 입력된 적 없는(`unknown`) 음식 제한·알레르기를 합성값(`none` 포함)으로 채우는 것뿐이다. 이미 값이 있는 항목은 바꾸지 않는다. 그 결과 네 명의 공통 식비 구간이 없거나 음식 조건이 `specified`이면 회차를 만들기 전에 `FAIL shared_meal_budget`·`FAIL food_conditions_none`으로 멈춘다. 최소 점수 미달이면 `check-matching`이 `FAIL participant_0N_seated code=...`로 멈춘다. 이때 `--normalize-profiles`를 주면 네 계정의 매칭 관련 항목(출생연도·성별·직업·MBTI·관심사·성향·식비·음식 조건)을 고정 합성값으로 덮어쓴다(이름·표시명·연락처·Instagram은 유지). 심사 시연 화면에 보이는 합성 프로필이 바뀌므로 사용자가 결정한다.

## 운영 데이터에 남는 것

정리·삭제·환불하지 않는다. 환불·취소 정책을 새로 만들지 않는다. `run` 한 번마다 다음이 운영 DB에 남는다.

- 회차 1개(지역 기본 `hongdae`, 시작·종료가 실행 시각 근처, 정원 4)와 그 회차의 검증 재고 1건(`배포 12단계 검증 식당`, 합성 주소). 모집 중인 몇 분 동안 다른 참가자 화면에도 보이고 신청도 가능하다(`--confirm-public-slot` 필요).
- 운영자 감사 기록 2건(`event_slot.create`, `venue_inventory.create`).
- 네 합성 계정의 신청 4건(확정 상태로 유지), 1회권 모의 결제 PAID 4건(실제 청구 없음, 9,900원 표시)과 사용된(USED) 1회권 4개. 활성 멤버십이 있는 계정은 결제 대신 멤버십이 쓰인다.
- 매칭 실행 1건·테이블 1개·좌석 배정·식당 배정·단체방 1개, 시스템 메시지(확정·식당·리마인드·대화 주제)와 참가자별 앱 알림.
- `participant-01`의 방 메시지 1건("안녕하세요, 배포 검증 메시지입니다.").
- 체크인 4건, 만족도 3건(`participant-01`은 한 번 수정), 하루 뒤 `participant-04`의 후기 리마인드 알림 1건.
- 이 네 명은 서로 "이미 만난 사이"로 기록되어 이후 매칭에서 새로운 사람 점수가 낮아진다. 사람별 선호·신고·차단·제재는 만들지 않는다.
- 기본 동작에서 비어 있던 프로필·동의 항목이 채워지고, `--normalize-profiles`를 주면 위 항목이 덮어써진다.
- 11단계 확인을 위해 두 번째 `run`을 하면 위 목록이 한 벌 더 생긴다.

## 로컬 실행 결과 (운영 통과 아님)

2026-10-19, 브랜치 `claude/w10-t2-deploy-verifier`(기준 `4559215`), 로컬 PostgreSQL 컨테이너 `127.0.0.1:55432`의 전용 DB `serentable_w10_d`, `uvicorn`(`127.0.0.1:8001`, `APP_ORIGIN=http://127.0.0.1:8001`)과 별도 프로세스 `python -m serentable.worker` 상시 루프, `seed_demo_accounts`로 만든 합성 계정. 스크립트는 `python3 -I`(외부 패키지 없음)·`--allow-local-http`로 실행했다.

- `run`(마감 1분·시작 마감 후 1.5분·길이 1.5분): `prepare`·`check-matching`·`check-event` 전체 PASS, 종료 코드 0. 첫 시도는 새 계정의 음식 조건이 `unknown`이라 `FAIL food_conditions_none`으로 회차 생성 전에 멈췄고, 입력된 적 없는 음식 조건을 채우도록 고친 뒤 통과했다.
- 같은 slot id로 `prepare`·`check-matching`·`check-event` 재실행: 전부 PASS(재전송이 같은 신청·결제·메시지·체크인을 반환). `check-feedback-reminder`는 `WAIT feedback_reminder_due <종료+24시간>`, 종료 코드 3.
- 단계별 실행: `prepare`(마감 3분) 직후 `check-matching --timeout-seconds 10`은 `WAIT matching_time`·종료 코드 3, 마감 전 `prepare --slot-id` 재실행 PASS, 이후 `check-matching`·`check-event` 각각 PASS.
- 11단계: 두 번째 `run --previous-slot-id <첫 회차>` 전체 PASS, 두 번째 테이블 `new` 0.00(첫 회차 100.00), 최소 점수 이상으로 확정.
- 후기 리마인드: 로컬 DB에서만 첫 회차의 네 시각을 SQL로 25시간 앞당기는 시험 고정 장치를 쓴 뒤 `check-feedback-reminder` PASS(`participant-04` 리마인드 1건). 운영에서는 실제로 24시간을 기다려야 하며 시각을 바꾸지 않는다.
- 설정 거절: `http://` 비루프백 주소, `--allow-local-http` 없는 로컬 HTTP, 시작이 마감 후 24시간 이상, 비밀번호 없음은 종료 코드 2.
- 순수 함수 시험 `tests/test_verify_deployed_twelve_step.py` 15 passed(주소 검증·출력 가림·요청 키·비공개 값 탐지·식비 구간).

### 검토 반영 후 재실행 (2026-10-19, 브랜치 `claude/w10-review-fixes`)

같은 로컬 구성(전용 DB `serentable_w10_d`, `127.0.0.1:8001` uvicorn + 별도 worker 루프, `python3 -I`, `--allow-local-http`)으로 다시 실행했다. 시험 DB에 남아 있던 기존 합성 계정은 시험용 비밀번호를 쓰므로 그 값으로 실행했다(첫 시도는 다른 비밀번호로 `FAIL operator_login` 후 로그인한 계정이 없어 로그아웃 정리 없이 끝났다).

- `run`(마감 1분·시작 마감 후 1.5분·길이 1.5분): PASS 127줄, 종료 코드 0. 동료 목록 4명·표시명만, 네 명의 이 테이블 알림(`table_id`) PASS, 마감 후 운영자 조치 0건. 같은 계정이 이전 실행에서 이미 만난 사이라 `new` 0.00.
- 같은 slot id로 `prepare`·`check-matching`·`check-event` 재실행 각각 종료 코드 0, `check-feedback-reminder`는 `WAIT feedback_reminder_due`·종료 코드 3.
- 로컬 DB에서만 그 회차의 네 시각을 SQL로 25시간 앞당긴 뒤 `check-feedback-reminder` PASS(이 테이블의 `participant-04` 리마인드 1건). 운영에서는 시각을 바꾸지 않는다.
- 비루프백 HTTPS 주소에서 `--confirm-public-slot` 없는 `run`은 요청 전에 `FAIL confirm_public_slot_required`, 종료 코드 2.
- `tests/test_verify_deployed_twelve_step.py` 32 passed(위 항목 + 재시도 범위·CSRF 재사용·로그아웃 정리·테이블별 알림·운영자 조치 판정·회차 응답 유실 복구·동료 목록·공개 회차 확인).

위 결과는 로컬 HTTP·로컬 DB·로컬 worker의 결과다. Railway의 HTTPS 프록시·`__Host-` 쿠키·운영 worker 주기·운영 데이터 상태(기존 프로필·멤버십·이전 만남)에서의 통과를 뜻하지 않는다. 배포 환경 12단계는 사용자가 위 절차를 실행해 결과를 기록하기 전까지 **미완료**다.

## 사용자가 남은 일

1. Work7~9 기능이 포함된 커밋의 운영 배포 확인(마이그레이션 포함).
2. 컨테이너에서 실제 사용자가 없는 시간에 `run --confirm-public-slot` 실행 → 결과 줄과 slot id 기록(비밀값·응답 본문은 기록하지 않음).
3. 종료 24시간 후 7일 안에 `check-feedback-reminder --slot-id <id>` 실행.
4. 필요하면 첫 회차 종료 후 `run --confirm-public-slot --previous-slot-id <id>`로 11단계 확인(데이터 한 벌 추가).
5. 결과를 이 문서와 인수 매트릭스에 실제 배포 커밋·시각과 함께 기록. 실기기 푸시·배포 브라우저 흐름은 별도 인수다.
