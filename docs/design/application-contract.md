# 일정 신청 계약 (Work #4 Task ①-b)

**기준:** 2026-10-16, Asia/Seoul. 위치: 참가 신청·이용권·결제 → 일정 신청·이용권·모의 결제 → ①-b 일정 신청(Issue #4). [핵심 데이터 모델](./core-data-model.md)의 Application·ApplicationCandidate·신청 상태, [UI 흐름](./ui-flow-design.md)의 `/participant/apply`·`/participant/apply/review`, [구현 명세](./mvp-implementation-spec.md) APP-01~03, [회차 계약](./event-slot-contract.md)을 따른다.

## 범위와 결정

- 신청(Application) 하나는 참가자가 직접 고른 모집 중 회차(EventSlot) 1~20개를 후보(ApplicationCandidate)로 보존한다. 회차 ID만 받으며 날짜×지역 곱집합을 만들지 않는다. 상한 20은 기술 결정이다.
- 상태는 PRD의 DRAFT/SUBMITTED/CANCELED를 DB CHECK로 고정한다. 검토 단계는 화면 메모리에서만 유지하고 서버는 제출 시 바로 SUBMITTED를 만든다(DRAFT 저장 API 없음, 기술 결정). 검토 화면을 새로고침하면 선택이 사라지고 선택 화면으로 안내한다.
- 제출 조건(APP-03): 본인 프로필 `complete`, 필수 동의(`privacy`·`operation` 현재 버전 수락) 완료, 모든 후보의 `closes_at > 현재`. 제출 때 근거로 쓴 최신 동의 기록 ID를 신청에 저장한다. **제출은 결제가 아니다.** 결제·이용권은 Task ①-c [이용권·모의 결제 계약](./payment-contract.md)에서 다룬다.
- 중복 방지(확정 범위): 같은 참가자는 같은 회차를 살아 있는(취소되지 않은) 신청 두 건에 동시에 둘 수 없다. 서로 겹치지 않는 회차로 별도 신청을 내는 것은 막지 않는다.
- 같은 요청 재전송: 클라이언트가 만든 `request_key`(UUID)가 같고 후보 집합이 같으면 이전 신청을 200으로 그대로 반환한다(상태가 바뀌었으면 바뀐 상태 그대로, 회차가 그 사이 마감돼도 동일 결과). 같은 키로 다른 후보를 보내면 409. 화면은 선택이 바뀔 때마다 새 키를 만든다.
- 참가자 취소: 본인 SUBMITTED 신청을 후보 중 가장 이른 신청 마감 전까지 CANCELED로 바꾸고 같은 트랜잭션에서 후보 소유를 해제한다. 이미 취소된 신청은 같은 결과를 반환한다. 환불·결제 취소(U04)와 확정 이후 취소(U13)는 범위 밖이다.
- 운영자는 전체 신청을 읽기만 한다. 운영자 수정·취소 API는 없다.

## 미결정 (U07, 이 Task에서 정하지 않음)

- 한 신청의 여러 후보 중 어느 회차가 소유권을 갖는지, 마감이 다른 후보 간 경쟁·확정 순서.
- 서로 다른 회차라도 시간이 겹치는 두 신청의 허용 여부(사용자 단위 동시 참여 충돌의 시간 범위).
- 매칭 시작 후 후보 회차가 바뀌거나 회차가 수정·취소될 때의 처리.
- 위 규칙은 매칭 Work(A3)에서 U07 결정과 함께 정한다. 현재 구현은 "같은 회차 이중 보유 금지"만 강제한다.

## 저장과 경합

| 대상 | DB 보장 | API 보장 |
|---|---|---|
| 재전송 동일 결과 | `application_user_request` UNIQUE(user_id, request_key) | 참가자 행 `FOR UPDATE`로 직렬화 후 키 조회, 후보 집합 비교 |
| 같은 회차 이중 보유 금지 | `application_candidate_live_user_slot` 부분 UNIQUE(user_id, event_slot_id) WHERE live | 같은 잠금 안에서 살아 있는 후보 조회 → 409 |
| 후보 소유자 = 신청 소유자 | 복합 FK (application_id, user_id) → application(id, user_id) | 본인 세션으로만 생성 |
| 제출 근거 | SUBMITTED/CANCELED는 submitted_at·동의 기록 FK NOT NULL, CANCELED ⇔ canceled_at | 프로필·동의·모집 중 재검증 |

잠금은 참가자 한 명 단위라 다른 참가자의 신청과 경합하지 않는다. 잠금을 우회한 경우에도 위 제약이 409로 정리된다.

## API

| API | 권한 | 입력/결과 |
|---|---|---|
| POST /api/me/applications | 참가자 + CSRF | `{request_key: UUID, event_slot_ids: UUID[1..20], 중복 없음}` → 새 신청 201 / 같은 요청 재전송 200 `{application}`. 형식 오류 422, 마감·없는 회차 422(`loc:["body","event_slot_ids"]`, type `slot_not_recruiting`), 프로필 미완성 409 `profile_incomplete`, 동의 미완료 409 `consent_incomplete`, 같은 회차 보유 409 `application_slot_duplicate`, 키 재사용 409 `request_key_reused` |
| GET /api/me/applications | 참가자 | 본인 신청만 `{applications:[Application]}` 최신순 |
| POST /api/me/applications/{id}/cancel | 참가자 + CSRF | 본인 신청 → 200 `{application}`. 타인·없는 ID 404 `application_not_found`, 가장 이른 마감 경과 409 `application_cancel_closed` |
| GET /api/admin/applications | 운영자 | 전체 `{applications:[Application & {participant:{id,login_id}}]}` 읽기 전용 |

`Application = {id, state, submitted_at, canceled_at, candidates:[EventSlot]}`(후보는 시작 시각순, EventSlot은 [회차 계약](./event-slot-contract.md) 형식). ①-c 이후 `payments`·`coverage`·`payment_required`가 추가됐다([결제 계약](./payment-contract.md)). 판정 순서는 인증 401 → 역할 403 → CSRF 403 → 본문 422 → 재전송 → 프로필 → 동의 → 회차 → 중복. 응답은 `Cache-Control: no-store`.

## 화면

- `/participant/apply`: 모집 중 회차를 체크박스로 복수 선택 → "선택 확인".
- `/participant/apply/review`: 선택 후보 목록, "제출은 결제가 아님·후보 간 배정 규칙 미정" 안내, "신청 제출"/"선택 수정". 오류 시 선택 유지, 마감 회차는 목록 재조회 후 제외.
- `/participant`: "내 신청" 목록과 상태(`신청 완료`, `신청 취소됨`. ①-c부터 결제 상태는 별도 "결제:" 줄), 취소 가능할 때만 "신청 취소".
- `/admin/applications`: 운영자 읽기 전용 "신청 현황".

## 검증

실제 PostgreSQL API 시험 `tests/test_applications.py`(복수 후보 제출·본인 조회, 프로필/동의/마감/형식 거절과 부분 저장 없음, 재전송 동일 결과·키 재사용·같은 회차 중복 거절·타 참가자 독립, 동일 요청 6건 동시 → 신청 1건, 다른 키 6건 동시 같은 회차 → 1건, 마감 전 취소·재신청·마감 후 취소 거절·타인 404, 운영자 목록과 역할·CSRF 거절)와 브라우저 E2E `frontend/e2e/applications.spec.ts`(후보 2개 선택→검토→동의 미완료 안내→선택 유지→제출, 내 신청 상태, 360/1440px 넘침 없음, 운영자 목록, 취소, 참가자의 운영자 화면 거절). 마이그레이션 `0005_application` 되돌리기/재적용을 확인했다.

## 마감 판정과 잠금 (2026-10-16 독립 검토 반영)

- 제출·취소는 참가자(`app_user`) 또는 신청 행 잠금을 얻은 **뒤** DB 시각 `clock_timestamp()`로 마감을 판정한다. 잠금 대기 중 마감이 지나면 제출은 422 `slot_not_recruiting`, 취소는 409 `application_cancel_closed`다.
- 제출·취소는 후보 회차 행을 `FOR SHARE`로 잠근다. **후속 매칭 실행기(Work #5/#6)의 선행 조건:** 마감·매칭을 시작할 때 해당 회차 행을 `FOR UPDATE`로 잠그고 DB 시각으로 마감 이후임을 확인해야, 진행 중인 제출·취소가 모두 끝난 뒤의 신청 집합을 본다.
- 프로필 저장도 같은 `app_user` 잠금을 잡아, 완성 여부를 확인한 제출과 프로필 덮어쓰기가 서로 끼어들지 않는다.
- 신청 상태와 후보 `live`의 일치는 현재 코드 경로(제출·취소)만 보장한다. 운영자 취소나 실행기가 상태를 바꿀 때 같은 트랜잭션에서 `live`도 갱신해야 한다.
