# Work #7 알림·Web Push 전송 계약

2026-10-17. [공통 계약](gathering-contract.md)의 알림 분담 구현. 사용자 승인된 병렬 작업트리에서 구현하며 원본·운영 DB·운영 배포·실제 제공자 전송은 수행하지 않는다.

## HTTP와 작업 경계

모든 참가자 경로는 본인 participant 세션만 허용한다. 변경은 CSRF를 검사한다. 원 endpoint·auth·p256dh와 개인키는 응답하지 않는다. 입력 오류도 기존 전역 검증 처리기로 입력값을 제거한다.

- `GET /api/me/notifications`: `{notifications:[{id,kind,title,body,url,created_at,read_at,push_status}]}`, 최신100개. push_status는 accepted/pending/failed/unavailable/not_subscribed. accepted는 제공자 HTTP 수락이며 기기 수신을 뜻하지 않는다.
- `POST /api/me/notifications/{id}/read`: 본문 없음, `{id,read_at}`. 최초 읽음 시각 보존. 타인/없는 ID404.
- `GET /api/me/push-config`: `{public_key,configured}`. 키는 서버 개인키에서 도출한 공개키이며 미설정 시 null/false.
- `POST /api/me/push-subscriptions`: `{endpoint,keys:{p256dh,auth}}`, `{id,active:true}`. 같은 본인 endpoint 재등록은 같은 ID. 타인 endpoint409, 소유권 이전 금지.
- `DELETE /api/me/push-subscriptions/{id}`: `{id,active:false}`, 반복 동일. 타인/없는 ID404.
- `GET /api/admin/push-deliveries`: `{deliveries:[{id,notification_id,subscription_id,state,attempts,next_attempt_at,last_error_code,sent_at}]}` 최신200개. 운영자만.
- `GET /api/admin/gathering-exceptions`: `{exceptions:[{id,dining_table_id,kind,state,reason_code,created_at,updated_at}]}` 최신200개. 운영자만.

`enqueue_notification(connection,user_id,event_key,kind,title,body,url,now)`는 호출자 트랜잭션에 참여한다. `(user_id,event_key)` 및 `(notification_id,subscription_id)` 고유키로 알림·작업 중복을 방지한다. url은 `/participant`만 허용한다. 앱내알림은 구독·푸시 설정과 무관하게 저장된다. 미구독은 delivery가 없고 not_subscribed로 보인다.

`dispatch_notifications()`는 각 delivery 트랜잭션/행잠금을 소유하고 SKIP LOCKED로 여러 worker 경쟁을 분리한다. 외부 HTTP 전송과 DB commit은 원자적이지 않다. 제공자 수락 후 commit 전 프로세스 중단 시 재전송되어 중복 수신할 수 있는 at-least-once 경계다. 실제 수락 없이 SENT를 저장하지 않는다. 최초 포함3회, 실패 후1분/5분. 최종 FAILED와 event_key 고유 운영자 예외를 저장한다. 구독만료404/410은 구독 비활성+UNAVAILABLE, 미설정·기본 네트워크 비활성·미구독은 시도0 UNAVAILABLE로 실패재시도와 구분한다. UNAVAILABLE은 자동 재발송하지 않으며 설정 변경이 과거 안내를 소급 발송하지 않는다.

## 환경과 네트워크 제한

- `WEB_PUSH_VAPID_PRIVATE_KEY`: base64url 무패딩32바이트 P-256 private scalar를 환경변수로만 제공. 경로/파일로 해석하지 않는다.
- `WEB_PUSH_VAPID_SUBJECT`: `mailto:` 연락 주소.
- `WEB_PUSH_NETWORK_ENABLED=true`: 실제 전송 허용. 기본 비활성. 운영/실기기 전송 승인은 이번 구현 범위에 없다.
- pywebpush2.5.0/py-vapid1.9.6의 암호화·VAPID 서명을 재사용한다. 공개키는 개인키에서 도출하여 불일치를 막는다. 단말 잠금화면 payload와 서비스 워커 표시/클릭은 일반 새 안내+고정 `/participant`; 개인이름·연락처·장소·테이블정보를 넣지 않는다.

정확한 허용 호스트는 `fcm.googleapis.com`, `updates.push.services.mozilla.com`이다. HTTPS443만, userinfo/IP/fragment/control/backslash 거부. auth16바이트·p256dh65바이트 엄격 base64url과 P-256 곡선점 검증. Apple은 공식 자료가 wildcard만 명시하여 정확 host 근거가 확보되지 않아 현재 미지원이다. 그 외 공급자도 거부한다.

매 실제 전송 시 endpoint를 다시 검사하고 DNS 모든 A/AAAA의 global 여부와 IPv4-mapped IPv6 거부를 검사한다. 검사한 sockaddr로 직접 socket 연결해 DNS 재바인딩 재해석을 막고 원호스트 SNI/인증서 검증을 사용한다. 표준 HTTPSConnection 직접접속으로 redirect·환경 proxy·netrc를 사용하지 않는다. socket/TLS/HTTP10초 timeout, 시스템 DNS resolver 자체의 총 지연 상한은 별도 보장하지 않는다. 제공자 본문·예외문자열을 저장/로그하지 않고 고정 오류 코드만 반환한다. 외부 전송 대역을 주입하는 session 인자는 격리 시험용이며 HTTP API에서 주입할 수 없다.

공식 근거(2026-10-17 확인): [pywebpush 소스·API](https://github.com/web-push-libs/pywebpush), [pywebpush 전송 구현](https://github.com/web-push-libs/pywebpush/blob/main/pywebpush/__init__.py), [Firebase 제공자 네트워크](https://firebase.google.com/docs/cloud-messaging/network-configuration), [Mozilla 제공자 목록](https://wiki.mozilla.org/Firefox/Services/), [Apple Web Push 네트워크 범위](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers).

## 검증 증거와 남은 항목

전용 PostgreSQL17 `serentable_work7_notifications_test`, loopback55432, Python3.12.12 별도 작업트리 venv. transport 검증 RED는 모듈 부재, API RED는 enqueue 함수 부재, 서명 전달 RED는 py-vapid raw bytes 입력 불일치로 실제 확인했다. 수정 후 `PYTHONPATH=backend TEST_DATABASE_URL=<전용DB> uv run pytest tests/test_notifications.py -q`: 9 PASS. 실제PG public API의 익명/CSRF/소유권·읽음/구독/해제 멱등·중복enqueue·3회1분/5분/최종 단일예외·410비활성·미설정·기본네트워크비활성·외부fake 암호화/VAPID 수락·mixed DNS거부·별도 dispatch 프로세스 검증이다. fake 성공은 기기 수신 증거가 아니다. Node26 호스트 `npm run build --prefix frontend` PASS; 통합 Node22와 브라우저 동작은 메인 담당의 후속 검증이다. 프런트엔드는 기존 화면/디자인 토큰을 사용하며 새 디자인 시스템을 추가하지 않는다.

실제 provider 네트워크/실제 지원 기기·권한 UI·Chrome/iOS 수신, 운영 환경설정·배포·운영 마이그레이션은 미검증. 실기기 수신을 INF-01 완료로 기록하지 않는다. 총 실패 후 예외만 제공하며 자동 재발송/수동 retry 관리 API는 범위에 없다.

Blaybus 위치: 모임 안내·피드백·재방문 → 식당·채팅·알림 → 배정·단체방·예약 메시지 구현 / 접근 권한·발송 실패 재시도 검증. 복사 문구: “앱내알림 영속·소유권·읽음/구독 멱등, 제공자 제한 Web Push 암호화·서명과 3회1분/5분 재시도·최종 예외를 격리PG/API/별도 실행기·외부 대역으로 검증. 실제 지원 기기 수신과 운영 반영은 미완료.” 별도 PR 없이 메인 통합 PR에 연결하며 Work #7 전체는 진행 중이다.
