# Work #8 참석·피드백·다음 추천 계약

결정은 [ADR-0014](../adr/0014-attendance-feedback-safety.md)를 따른다. 근거 요구는 [구현 명세](mvp-implementation-spec.md)의 FDB-01~04·SAF-01~02·RET-01~02다. 통합 브랜치는 `claude/work8-feedback`(Issue #8)이고 스키마는 `migrations/versions/0012_feedback.py`(T0)다.

## 공통 규칙

- **대상:** 대상 테이블은 `match_participation.state='CONFIRMED'`이고 `table_assignment.ended_at IS NULL`인 확정 배정이다. 같은 테이블의 다른 확정 참가자만 "같은 테이블 참가자"다.
- **화면 노출:** 상대는 표시명(`participant_profile.data->>'display_name'`, 없으면 "참가자")만 보인다. 연락처·Instagram·평가·선호·신고는 상대에게 보이지 않는다.
- **쓰기 API:** 모든 쓰기 API는 CSRF 의존성(`require_csrf_participant`/`require_csrf_operator`)을 쓴다. 같은 요청을 다시 보내도 결과는 같다. 이미 저장된 경우 같은 상태를 응답한다.
- **시각:** 시각 판단은 DB 시계(`clock_timestamp()` 또는 트랜잭션 `now()`)를 쓴다.
- **제외 관계 기록:** `participant_exclusion`은 `user_low < user_high` 정렬로 `ON CONFLICT DO NOTHING` 기록한다. 모든 출처(`avoid`, `block`, `report`)는 공용 함수 `serentable.safety.record_exclusion(connection, a, b, source)`로 기록한다. 이 함수는 T0이 제공한다.

## 스키마 0012 (T0)

| 표 | 핵심 |
|---|---|
| `attendance_check_in` | (dining_table_id, user_id) PK, checked_in_at |
| `no_show_review` | (dining_table_id, user_id) PK, decision `CONFIRMED_NO_SHOW`/`EXCUSED`, reviewed_by, reviewed_at |
| `table_feedback` | (dining_table_id, user_id) PK. table·conversation·venue 평점 1~5, rejoin_intent·recommend_intent 1~5, submitted_at |
| `person_preference` | (dining_table_id, rater_id, target_id) PK, choice `MEET_AGAIN`/`AVOID`, rater≠target |
| `safety_report` | id, reporter_id, reported_id, dining_table_id NULL, reason_code, detail(≤1000) NULL, state `OPEN`/`CONFIRMED`/`DISMISSED`, reviewed_by/at |
| `participant_sanction` | id, user_id, kind `WARNING`/`SUSPENSION`/`PERMANENT_BAN`, report_id NULL, ends_at(SUSPENSION만 필수), created_by, created_at |
| `participant_exclusion.source` | 기존에 `report` 추가 |

## 티켓 그래프

각 티켓은 자기 파일만 소유한다. T0이 라우터 등록과 화면 경로를 미리 만들었으므로 `main.py`·`main.tsx`는 수정하지 않는다. 스키마가 부족하면 직접 바꾸지 말고 메인에 보고한다.

| 티켓 | 소유 파일 | 차단 |
|---|---|---|
| T1 체크인·노쇼 | `backend/serentable/attendance.py`, `frontend/src/attendance.tsx`, `tests/test_attendance.py` | T0 |
| T2 평가·사람별 선호·미응답 리마인드 | `backend/serentable/feedback.py`, `frontend/src/feedback.tsx`, `tests/test_feedback.py` | T0 |
| T3 신고·차단·운영자 제재 | `backend/serentable/safety.py`(공용 함수 유지), `frontend/src/safety.tsx`, `tests/test_safety.py`. 제재 중 신청 거절을 위해 `applications.py`의 신청 생성 경로 한 곳만 수정한다 | T0 |
| T4 이력·추천·다음 매칭 반영 | `backend/serentable/recommendations.py`, `frontend/src/history.tsx`의 이력·추천 영역, `tests/test_recommendations.py`. 상호 재만남 면제를 위해 `matching.py`의 `MET_SQL` 한 곳만 수정한다 | T1, T2, T3 |
| B 브랜드 자료 적용(Work #7) | `frontend/src/style.css`, 정적 자산, `docs/design/ui-brand-review.md` | 없음 |

### T1 체크인·노쇼 (FDB-01, U15)

- `POST /api/me/tables/{table_id}/check-in`: 시작 30분 전부터 종료까지만 허용한다. 창 밖이면 409 `check_in_closed`, 비멤버면 404다.
- `GET /api/admin/no-show-candidates`: 종료 시각이 지났고, 체크인이 없고, 검토가 없는 확정 참가자 목록이다.
- `POST /api/admin/no-show-candidates/{table_id}/{user_id}`: `CONFIRMED_NO_SHOW` 또는 `EXCUSED`를 한 번 기록한다.
- 화면: 참가자 이력 카드의 체크인 버튼, 운영자 안전 화면의 노쇼 후보 영역.

### T2 평가·선호·리마인드 (FDB-02~04, §15)

- `PUT /api/me/tables/{table_id}/feedback`: 종료 이후에만 받는다. 5개 평점을 받고 수정할 수 있다.
- `PUT /api/me/tables/{table_id}/preferences`: 같은 테이블 참가자별 `MEET_AGAIN`/`AVOID`/해제를 받는다. 종료 후에만 허용한다. `AVOID`를 같은 트랜잭션에서 `record_exclusion(..., 'avoid')`로 기록한다. 해제해도 이미 기록된 제외 관계는 유지한다(안전 우선).
- `GET /api/me/tables/{table_id}/feedback`: 본인 입력과 같은 테이블 참가자 표시명을 돌려준다.
- 미응답 리마인드: 종료 후 24시간이 지나도 평가가 없으면 `app_notification`을 1회 만든다. 이벤트 키는 `feedback-reminder:{table}`다. `run_feedback_jobs()`는 T0의 worker 연결에서 호출된다. 24시간은 구현 기본값이다.
- 미응답이어도 신청은 막지 않는다.

### T3 신고·차단·제재 (SAF-01~02, U09)

- `POST /api/me/reports`: 같은 테이블이었던 상대만 신고할 수 있다. 접수와 같은 트랜잭션에서 `record_exclusion(..., 'report')`를 기록한다.
- `POST /api/me/blocks`: 같은 테이블이었던 상대에게 `record_exclusion(..., 'block')`을 기록한다.
- 운영자 API:
  - `GET /api/admin/reports`
  - `POST /api/admin/reports/{id}/review`: `CONFIRMED`/`DISMISSED`
  - `POST /api/admin/sanctions`
  - `GET /api/admin/sanctions`
- 활성 `SUSPENSION`(ends_at 이전)·`PERMANENT_BAN` 사용자의 새 신청은 403 `participation_restricted`다.
- 피신고자 API·화면 어디에도 신고 존재가 드러나지 않는다.

### T4 이력·추천·반영 (RET-01~02, §18-11)

- `GET /api/me/history`: 과거 확정 테이블 목록이다. 날짜·지역·체크인 여부·평가 제출 여부·현재 체크인/평가 가능 여부를 돌려준다.
- `GET /api/me/recommendations`: 신청 가능한 미래 회차를 정렬하고 각각 `reason`을 붙인다.
  - 1순위: 본인 table 평점 평균 4 이상인 지역·요일
  - 2순위: 참석한 지역
  - 그다음: 시작 시각
- `MET_SQL`: 서로 `MEET_AGAIN`을 고른 쌍은 이전 만남에서 뺀다.
- 실제 PG 시험: 한 회차의 피드백 이후 다음 회차 매칭에서 AVOID 쌍은 분리, 상호 재만남 쌍은 '새로운 사람' 감점 없음.

## 검증

- 티켓마다 TDD(RED→GREEN)로 실제 PostgreSQL API 시험을 한다. 각 티켓은 자기 격리 DB `serentable_w8_<티켓>`을 쓴다.
- Playwright는 포트 8000을 공유하므로 티켓 단계에서 실행하지 않는다. 통합 후 메인이 실행한다.
- 운영 DB·원본·보존 데모 DB는 사용하지 않는다.
