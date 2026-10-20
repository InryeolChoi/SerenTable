# Work #7 식당·채팅·알림 구현 계약

2026-10-17. 모임 안내·피드백·재방문 → 식당·채팅·알림 (#7). 기존 Task: 제공 브랜드 자료 적용 / 배정·단체방·예약 메시지 구현 / 접근 권한·발송 실패 재시도 검증. 사용자 명시 병렬 구현 요청에 따라 이 Work 안에서 구현 에이전트가 별도 브랜치·작업 트리로 분담한다(일반 AGENTS의 메인 직접 구현 원칙에 대한 이번 요청의 예외). Work/Task는 추가하지 않는다. 통합 시작 e3d4240, 선행 PR #40 CI39023922837 SUCCESS. 운영 migration/deploy/매칭/데이터 변경 금지 유지.

## 승인 정책과 기술 경계

- U10 사용자 승인: 가격대는 전원이 허용해야 하며, 음식/알레르기가 모두 명시 none이거나 해당 테이블·현재 음식 조건 스냅샷에 대해 운영자가 적합성을 확인한 가상 재고만 배정한다. unknown/자유 서술을 AI가 안전 판정하지 않는다. 재고/공통 예산/확인 부족은 예외다. 실제 예약 API를 호출하지 않는다.
- U12 사용자 승인: 푸시 전송 최대 3회(최초 포함), 실패 후 1분/5분. 초과는 운영자 예외. 권한 거부·미지원·미구독·서버 미설정은 실패 재시도와 구분하고 앱 내 알림은 항상 저장한다. 실제 휴대폰 수신은 사용자 기기 검증이 필요하다.
- 채팅은 확인된 본인의 active table_assignment + match_participation.CONFIRMED만 접근. 영속 PostgreSQL 메시지, 커서 기반 2초 HTTP 폴링·재연결. 메시지 쓰기는 room FOR UPDATE 후 id 할당하여 뒤늦은 작은 id commit에 따른 누락을 막는다. 시스템 게시도 같은 잠금을 사용한다. 연락처/Instagram/제외 관계·상세 점수는 게시하지 않는다.
- 가상 재고는 event_slot별 예약 가능 테이블 하나를 한 행으로 나타낸다. allocation은 dining_table당 1개, inventory당 1개 UNIQUE. 확정은 변경하지 않고 후속 배정/방/안내를 별도 Worker 단계로 멱등 생성한다. 과거 운영 확정의 일괄 소급 처리는 운영 승인 전 실행하지 않는다.
- 명시 가격 구간: 10000<=가격<20000 / 20000<=가격<30000 / 30000<=가격. 전원 meal_budget_bands와 교집합 검증. 알려지지 않은 가격/음식은 배정하지 않는다.
- 날짜/시각은 DB 시각. 행사 하루 전 리마인드는 starts_at-24h, 시작 콘텐츠는 starts_at. 확정 시점이 하루 전을 지난 경우 미발송 리마인드를 즉시 준비한다. 행사 종료 후 새 리마인드/시작 콘텐츠를 소급 발송하지 않는다.

## 공통 스키마 0011_gathering (메인 담당)

- chat_room(id UUID PK, dining_table_id UUID UNIQUE FK, created_at timestamptz)
- chat_message(id BIGSERIAL PK, room_id FK, author_id nullable FK, kind SYSTEM|USER, request_key UUID nullable, event_key text nullable, body text, created_at timestamptz); UNIQUE(room_id,author_id,request_key), UNIQUE(room_id,event_key), kind shape CHECK. 본문1~2000자.
- app_notification(id UUID PK,user_id FK,event_key text,kind text,title text,body text,url text,created_at timestamptz,read_at nullable); UNIQUE(user_id,event_key)
- push_subscription(id UUID PK,user_id FK,endpoint text UNIQUE,p256dh text,auth text,created_at timestamptz,active bool). 원 endpoint/키는 JSON·로그에 반환하지 않음.
- push_delivery(id UUID PK,notification_id FK,subscription_id FK,state PENDING|SENT|FAILED|UNAVAILABLE,attempts int,next_attempt_at timestamptz,last_error_code nullable,sent_at nullable); UNIQUE(notification_id,subscription_id)
- gathering_exception(id UUID PK,dining_table_id nullable FK,event_key text UNIQUE,kind text,state OPEN|RESOLVED,reason_code text,created_at,updated_at timestamptz). 푸시 반복 실패도 event_key로 중복 방지. 운영자에는 안전한 코드만.
- venue_inventory(id UUID PK,event_slot_id FK,name,address,map_url,price_krw int,capacity int,active bool,created_by FK,created_at timestamptz)
- venue_food_approval(inventory_id FK,dining_table_id FK,food_snapshot text,reviewed_by FK,created_at timestamptz,PK(inventory_id,dining_table_id,food_snapshot))
- venue_allocation(id UUID PK,dining_table_id UNIQUE FK,inventory_id UNIQUE FK,reservation_name text,created_at timestamptz)

## 모듈 간 고정 인터페이스

채팅 담당: backend/serentable/chat.py router와 ensure_room(connection, table_id, now)->UUID; publish_system_message(connection,room_id,event_key,body,now)->int (재전송 동일 id). GET /api/me/rooms, GET/POST /api/me/rooms/{uuid}/messages. POST {request_key,body}, GET ?after_id=0&limit=100. 반환 rooms:[{id,dining_table_id,member_count,starts_at,region_name}], messages:[{id,kind,body,author:{display_name}|null,created_at}], next_cursor. 본인 아닌 방404/운영자403. 사용자 동일키다른본문409. frontend/src/chat.tsx RoomsPage export. main 라우팅/메뉴 등록은 메인이 담당.

알림 담당: backend/serentable/notifications.py router와 enqueue_notification(connection,user_id,event_key,kind,title,body,url,now)->UUID. db영속/구독별 delivery생성; dispatch_notifications()가 자체트랜잭션과 외부전송 경계를 소유. GET /api/me/notifications, POST /api/me/notifications/{uuid}/read; GET /api/me/push-config (public key only), POST /api/me/push-subscriptions (본인 구독), DELETE /api/me/push-subscriptions/{uuid}; GET /api/admin/push-deliveries, GET /api/admin/gathering-exceptions. 본문은 구현 시 고정 문서에 추가. frontend/src/notifications.tsx NotificationsPanel export; frontend/public/sw.js 푸시·클릭. 의존성 pyproject/uv.lock은 알림 담당만 수정. Worker와 main.tsx 등록은 메인 담당. 아직 외부 전송을 실제 실행하지 않는다.

메인 담당: migrations/versions/0011_gathering.py, gatherings.py (가상 재고/음식 확인/배정/예약 공지/맞춤주제3개·아이스브레이킹/리마인드·시작 게시), gatherings.tsx, main.py/main.tsx/worker.py 통합, 계약·ADR·인계/PR·Issue·E2E. Worker: 매칭 이후 run_gathering_jobs(), 이후 dispatch_notifications(). 방은 확정 테이블당 반드시1개, 배정 실패여도 방+실패 상태는 확인 가능. 방 게시/앱내알림은 같은 트랜잭션.

## 검증과 완료 기준

기존 승인 경계인 실제 PG API·별도 Worker 외부 행동 및 브라우저 E2E를 유지한다. 각 담당은 TDD로 RED→GREEN, 개별 새 격리 DB를 사용하고 같은 DB를 동시에 초기화하지 않는다. 멤버십·소유권·CSRF·실패 롤백·재전송·중복 방/공지/알림·재연결 커서·좌석 중복 소비·음식/가격 거절·푸시 재시도/최종 예외를 검증한다. 사용자 제공 원본/기존 로컬 보존 DB·운영 연결을 쓰지 않는다. mock 푸시 성공은 기기 수신 증거가 아니다.

## 2026-10-20 감사 수정 계약

A3 승인 [ADR-0017](../adr/0017-allocated-venue-condition-review.md)을 따른다. food_snapshot은 현재 음식·알레르기·정렬 허용 식비의 버전1 digest다. 신규 allocation은 마지막 확인 digest를 저장하고, 기존 NULL은 확인을 꾸미지 않고 재검토한다. worker는 조건 변경 예외를 열되 기존 배정·예약을 바꾸지 않는다. 현재 배정 inventory·최신 digest·전원 가격/좌석을 검증한 운영자 확인만 예외를 해소하며 감사와 원자적으로 저장한다. 일반 예외 resolve로 해소할 수 없다.

시작 주제는 합집합 첫 값 대신 2명 이상 공유한 관심사 중 공유 인원이 많은 항목, 동점 코드 순으로 고른다. 공통 없음은 일반 주제다. REMINDER 방/앱 본문에 서울 집합 시각·실제 식당/주소/예약명 또는 미배정·기존 취소/환불 및 미정 정책 안내를 포함한다. 잠금화면은 기존 일반 문구로 제한한다. [구현·검증](audit-remediation-2026-10-20.md).
