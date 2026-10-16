# 모집 회차·지역 계약 (Work #4 Task ①-a)

**기준:** 2026-10-16, Asia/Seoul. 위치: 참가 신청·이용권·결제 → 일정 신청·이용권·모의 결제 → ①-a 모집 회차·지역 설정. [핵심 데이터 모델](./core-data-model.md)의 EventSlot, [UI 흐름](./ui-flow-design.md)의 `/admin/events`, [공식 FAQ](./official-faq-2026-10-16.md) Q9를 따른다.

## 범위와 결정

- 지역은 FAQ Q9의 서울 4곳(`hongdae` 홍대, `jamsil` 잠실, `gangnam` 강남, `euljiro` 을지로)을 마이그레이션으로 고정한다. 서울 외 지역은 승인되지 않아 운영자가 지역을 추가하지 않는다.
- 회차(EventSlot)는 지역 하나, 시작·종료·신청 마감·매칭 예정 시각, 정원을 가진다. 시각은 시간대가 있는 절대 시각으로 저장하고 응답은 `+09:00`(한국은 일광 절약 시간 없음) ISO 8601로 반환한다. 화면은 서울 기준 24시간제로 표시한다.
- 검증(기술 결정): `시작 < 종료`, `신청 마감 ≤ 매칭 예정 ≤ 시작`(명세의 "회차별 마감 시각에 실행"), 생성 시 신청 마감은 현재 이후, 정원 4~100명(테이블 최소 4명, 실행당 100명 검증 목표). 같은 지역·시작 시각은 DB 고유 제약으로 1건만 허용하며 동시 중복 제출도 409로 정리된다.
- 모집 상태는 저장하지 않고 `recruiting = 신청 마감 > 현재`로 계산한다.
- 회차 수정·취소는 신청이 생긴 뒤의 영향 검증(U07/U13)과 함께 ①-b 이후에 다룬다. 이 Task는 생성·조회만 제공한다.

## API

| API | 권한 | 입력/결과 |
|---|---|---|
| GET /api/admin/regions | 운영자 | `{regions:[{code,name}]}` 정렬 고정 |
| POST /api/admin/event-slots | 운영자 + CSRF | `{region_code,starts_at,ends_at,closes_at,matches_at,capacity}` (시각은 오프셋 필수) → 201 `{event_slot}`. 형식·순서·정원 위반 422, 미등록 지역 422(`loc:["body","region_code"]`), 지난 마감 422(`loc:["body","closes_at"]`), 중복 409 `event_slot_duplicate` |
| GET /api/admin/event-slots | 운영자 | 전체 `{event_slots:[EventSlot]}` (마감된 회차 포함) |
| GET /api/event-slots | 참가자 | 신청 마감 전 회차만 `{event_slots:[EventSlot]}` |

`EventSlot = {id, region:{code,name}, starts_at, ends_at, closes_at, matches_at, capacity, recruiting}`. 인증 401, 역할 403, CSRF 403은 본문 검증보다 먼저 판정한다([계정 계약](./account-profile-contract.md)). 응답은 `Cache-Control: no-store`.

## 검증

실제 PostgreSQL API 시험 `tests/test_event_slots.py`(생성·서울 시각 응답·참가자 조회, 입력 검증과 부분 저장 없음, 동시 중복 4건 중 1건만 생성, 역할·CSRF 거절, 마감 후 참가자 목록 제외)와 브라우저 E2E `frontend/e2e/events.spec.ts`(운영자 생성·순서 오류 안내·중복 안내, 참가자 조회, 360/1440px 넘침 없음, 참가자의 운영자 화면 거절).
