# 이용권·모의 결제 계약 (Work #4 Task ①-c)

**2026-10-17 취소 경합 보완:** 결제는 참가자 잠금 뒤 신청의 `FOR NO KEY UPDATE`를 얻고 최신 SUBMITTED 상태를 확인한다. 취소가 먼저 끝나면 409 `application_not_payable`이며 결제·이용권을 추가하지 않는다. 매칭 배치 FK의 `FOR KEY SHARE`와 호환되는 잠금이다. CEO 확인 대기 U03/U04는 미정으로 유지한다.

**기준:** 2026-10-16, Asia/Seoul. 위치: 참가 신청·이용권·결제 → 일정 신청·이용권·모의 결제 → ①-c 이용권·모의결제(Issue #4). [핵심 데이터 모델](./core-data-model.md)의 Payment·Entitlement·결제 상태, [구현 명세](./mvp-implementation-spec.md) APP-04·PAY-01/02·STA-01과 U03/U04 행, [공식 FAQ](./official-faq-2026-10-16.md) Q1·Q4·Q5, [ADR-0007](../adr/0007-prd-ticket-scope.md), [신청 계약](./application-contract.md)을 따른다.

## 범위와 결정

- **실제 PG 결제가 아니다.** 카드·계좌 정보를 받지 않으며 화면은 "모의 결제 · 실제 결제가 발생하지 않습니다"를 표시한다. 모든 결제 응답에 `mock: true`.
- 상품(FAQ Q4, 상품 버전 `faq-2026-10-16`): 1회권 9,900원, 멤버십 1/3/6개월 35,000/75,000/120,000원. 결제 행에 상품 코드·이름·종류·버전·금액·기간(개월)을 스냅샷으로 저장해 이후 가격 변경이 과거 결제를 바꾸지 않는다. 상품표는 코드 상수이며 운영자 수정 화면은 없다.
- 결제(Payment)는 신청(Application) 하나에 속한다(ERD Payment.application_id). SUBMITTED 신청만 결제할 수 있다.
- 결제 상태는 PRD 중 **PENDING → PAID / FAILED만** 구현한다. 환불 상태(REFUND_*)는 U04·A3-W2 범위이며 DB CHECK에도 아직 없다. 모의 처리기는 동기식이라 PENDING 행을 넣고 같은 트랜잭션에서 PAID/FAILED로 바꾼다. 따라서 PENDING은 현재 외부에서 관찰되지 않으며 화면은 요청 중 "결제 처리 중…"을 표시한다(기술 결정, 비동기 PG 연동 시 확장).
- 실패 시뮬레이션: 요청의 `simulate_failure: true`(화면의 "실패 시뮬레이션" 체크)는 결정적으로 FAILED를 만들고 이용권을 부여하지 않는다. 실패 기록은 남고 새 요청 키로 다시 결제할 수 있다.
- 신청 취소는 환불이 아니다. 취소된 신청의 PAID 결제와 보유 1회권은 기록 그대로 남는다(환불·보관·재사용 U03/U04). 이용권 응답의 `application_state`로 취소된 신청에 묶인 1회권을 구분한다.
- **결제 마감:** 결제(멤버십 구매 포함)는 신청의 가장 이른 후보 신청 마감 전까지만 가능하다. 참가자 행 잠금 뒤 후보 회차 행을 `FOR SHARE`로 잠그고 DB 시각 `clock_timestamp()`로 판정하며, 마감 이후면 409 `payment_closed`. 결제·이용권의 시각(요청·완료·멤버십 시작/만료)도 같은 DB 시각을 쓴다. 후속 매칭 실행기가 회차 행을 `FOR UPDATE`로 잠그면 진행 중인 결제가 끝난 뒤의 상태를 본다.

## U03 임시 적용 (CEO 확인 대기, 정책 버전 `provisional-2026-10-16`)

`backend/serentable/payments.py`의 `ENTITLEMENT_POLICY_VERSION` 하나로 묶고 결제·이용권 행의 `policy_version`에 기록한다. 정책이 바뀌면 새 버전으로 구분한다.

- 멤버십은 **결제 완료 시각부터** 시작하고 **서울 기준 달력월**로 끝난다. 같은 서울 시각, 대상 월에 그 날짜가 없으면 말일로 보정한다(1/31 + 1개월 = 2/28, 윤년 2/29). 30일 환산을 쓰지 않는다. `add_calendar_months` 순수 함수로 시험한다.
- 1회권은 신청 결제 시 해당 신청에 **보유(HELD)** 되며 테이블 확정 시 사용 처리한다. 매칭이 아직 없으므로 사용 처리는 구현하지 않았다.
- 멤버십 매칭 실패 1회당 7일 연장은 구현·연결하지 않았다(MembershipExtension 테이블 없음).
- **임시(기술 결정), CEO 확인 대기** — 적용 범위·중복 구매·`membership_too_short`(U03 확정 시 재검토): 멤버십은 지금 유효하고, **가장 이른 후보 마감 이전에 시작했으며**, 만료 시각이 신청의 **모든 후보 회차 시작 시각보다 늦을 때** 그 신청을 포함한다. 마감 뒤 다른 신청을 위해 산 멤버십은 이미 마감된 신청을 소급해 포함하지 않는다. 포함되면 새 결제를 요구하지 않고(`payment_required: false`, `coverage.source: "membership"`) 결제 요청은 409 `entitlement_already_covers`. 가장 늦은 후보 시작 전에 끝나는 멤버십 구매는 409 `membership_too_short`. 기존 멤버십이 신청을 포함하지 않으면 새 멤버십을 결제할 수 있고 기존 기간과 별개로 결제 시각부터 계산한다(갱신·합산 규칙 미정). 위 세 규칙은 모두 임시이며 CEO 확인 전이다.
- 매칭 대상 여부는 회차별로 회차 마감 시점 기준으로 따로 판정한다([신청 계약](./application-contract.md) "매칭 대상 판정").
- 1회권은 결제한 신청에만 묶이며 다른 신청에 재사용하지 않는다.

## 미결정 (U04 및 U03 잔여, 이 Task에서 정하지 않음)

- U04: 환불 가능 판정·환불 상태 전이, 화요일 24:00 경계의 회차별 적용·매칭 마감과의 관계, 시스템 실패 환불 예외, 당일 취소. 화면은 결제 전 "현행 기준 화요일 24:00 이후 환불 불가 · 세부 환불 정책 미정"만 안내한다.
- U03 잔여: 갱신·자동 갱신, 환불 금액, 취소된 신청의 1회권 보관·재사용, 실패 연장의 실패 식별 규칙.

## 저장과 경합

| 대상 | DB 보장 | API 보장 |
|---|---|---|
| 같은 요청 재전송 | `payment_user_request` UNIQUE(user_id, request_key) | 참가자 행 `FOR UPDATE`로 직렬화 후 키 조회. 같은 신청·상품·실패 옵션이면 이전 결과 200, 다르면 409 `request_key_reused` |
| 신청당 진행 중/성공 결제 하나 | `payment_application_live` 부분 UNIQUE(application_id) WHERE state IN (PENDING, PAID). FAILED는 이력으로 남고 새 시도를 막지 않음 | 같은 잠금 안에서 PAID → 409 `payment_already_paid` |
| 결제 하나에 이용권 하나 | `entitlement_payment` UNIQUE(payment_id) | PAID 전이와 이용권 생성을 한 트랜잭션에서 처리 |
| 소유자 일치 | 복합 FK (application_id, user_id) → application, (payment_id, user_id) → payment | 본인 세션으로만 생성 |
| 상태·스냅샷 정합 | state CHECK, PENDING ⇔ completed_at NULL, 금액 ≥ 0, 1회권 기간 NULL·멤버십 기간 > 0, 이용권 종류별 모양(1회권: 신청 ID 필수·만료 없음, 멤버십: 만료 > 시작) | 상품표에서만 금액을 정함(요청의 금액 필드는 422) |

잠금은 참가자 한 명 단위라 다른 참가자의 결제와 경합하지 않는다.

## API

| API | 권한 | 입력/결과 |
|---|---|---|
| GET /api/products | 로그인 사용자 | `{mock:true, product_version, policy_version, products:[{code, name, kind, price_krw, period_months}]}` |
| POST /api/me/applications/{id}/payments | 참가자 + CSRF | `{request_key: UUID, product_code: single\|membership_1m\|membership_3m\|membership_6m, simulate_failure?: bool}` → 새 시도 201 `{payment}`(PAID 또는 FAILED) / 같은 요청 재전송 200. 형식 오류 422, 타인·없는 신청 404 `application_not_found`, 취소된 신청 409 `application_not_payable`, 후보 마감 경과 409 `payment_closed`, 이미 PAID 409 `payment_already_paid`, 멤버십이 포함 409 `entitlement_already_covers`, 기간 부족 409 `membership_too_short`, 키 재사용 409 `request_key_reused` |
| GET /api/me/entitlements | 참가자 | 본인 이용권 `{entitlements:[Entitlement]}` 최신순 |
| GET /api/me/applications, GET /api/admin/applications | 기존 | Application에 `payments`(최신순 전체 시도), `coverage`, `payment_required` 추가. 운영자는 읽기만 한다 |

`Payment = {id, application_id, state, mock, amount_krw, product:{code, name, kind, version, price_krw, period_months}, policy_version, simulated_failure, requested_at, completed_at}`. `Entitlement = {id, kind: SINGLE|MEMBERSHIP, product_code, payment_id, application_id(1회권만), application_state(1회권이 묶인 신청 상태, 멤버십 null), starts_at, expires_at(멤버십만), state: HELD|ACTIVE|EXPIRED, policy_version}`. `coverage = null | {source: "payment"|"membership", entitlement}`. 판정 순서는 인증 401 → 역할 403 → CSRF 403 → 본문 422 → 재전송 → 신청 소유 → 신청 상태 → 결제 마감 → 포함 여부 → 멤버십 기간. 응답은 `Cache-Control: no-store`.

## 화면

- `/participant/apply/review`: 후보 목록 아래 이용권 선택(가격·기간·무제한 안내)과 환불 안내. 제출 후 결제가 필요하면 같은 화면에 모의 결제 영역, 멤버십이 포함하면 "보유한 멤버십으로 결제 없이" 안내.
- 모의 결제 영역(`모의 결제` 영역): 실제 결제 아님 표시, 이용권 선택, 서버 상품표의 결제 금액, 환불 안내(화요일 24:00 이후 환불 불가·세부 환불 정책 미정), "실패 시뮬레이션" 체크, "모의 결제하기". 결과는 결제 완료(상태) 또는 결제 실패(경고)와 재시도.
- `/participant/payment/:applicationId`: 결제가 남은 신청을 나중에 결제한다. 새로고침해도 같은 화면이며 소유는 API가 검사한다.
- `/participant`: 내 신청마다 신청 상태와 별도의 "결제:" 줄(결제 필요/결제 완료/결제 실패·재시도 필요/멤버십 적용/결제 마감 · 미결제, 실패 횟수)과 "매칭:" 줄([신청 계약](./application-contract.md) "매칭 대상 판정"). "결제하기"는 결제가 필요하고 가장 이른 후보 마감 전일 때만 보인다. "내 이용권"에 종류·상태와 멤버십 시작·만료 시각, 취소된 신청의 1회권은 "취소된 신청에 묶여 보유"(자동 환불 아님·보관·재사용 미정)로 표시한다.
- 노쇼·취소 안내(PAY-02): 결제 전(신청 검토·모의 결제 영역)과 제출 후(`/participant`)에 환불 안내 옆에 "노쇼·취소 정책 미정"(노쇼 횟수·참여 제한·이용권 차감·당일 취소 미정, FAQ Q3/U04)을 표시한다.
- 상품 선택 설명에 U03 임시 규칙임을 "임시 적용 · 확정 전"으로 표시한다(내 이용권 영역과 같은 표기).
- `/admin/applications`: 신청마다 결제 상태를 읽기 전용으로 표시한다.

## 검증

실제 PostgreSQL API 시험 `tests/test_payments.py`(공식 가격 상품표, 1회권 결제와 스냅샷·보유, 재전송 동일 결과·키 재사용 3종 거절·이미 결제 거절, 실패 시뮬레이션 무권리·재전송·실패 후 재시도와 실패 기록 유지, 멤버십 달력월·후속 신청 포함·만료 후 미포함·기간 부족 거절, 동일 요청 6건 동시 → 결제 1건·이용권 1건, 서로 다른 키 6건 동시 같은 신청 → 1건 결제, 타인·취소·형식·역할·CSRF 거절, 운영자 읽기·취소 후 결제 유지), 순수 함수 `tests/test_entitlement_policy.py`(1/31·윤년·12→1월·서울 날짜 기준), 브라우저 E2E `frontend/e2e/payments.spec.ts`(이용권 선택→실패 시뮬레이션→재시도 결제 완료→멤버십으로 다음 신청 결제 없음→내 신청·내 이용권 표시→기간 밖 신청의 결제 화면 새로고침·기간 부족 안내→1회권 결제 후 신청 취소 시 "취소된 신청에 묶여 보유"→마감 뒤 미결제 신청에 "결제하기" 없음→운영자 결제·매칭 상태, 신청/결제/매칭 줄 분리·노쇼 정책 미정·U03 임시 표기, 360/1440px 넘침 없음). 마감·대상 판정 시나리오는 `tests/test_failure_and_duplicates.py`. E2E는 Playwright 웹 서버가 로컬 DB(127.0.0.1/localhost)일 때만 스키마를 `alembic downgrade base && alembic upgrade head`로 재생성한 뒤 시드하므로 이전 실행의 결제가 남지 않는다([운영 지침](../operations/foundation-runbook.md)). 마이그레이션 `0006_payment` 되돌리기/재적용을 확인했다.
