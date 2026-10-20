# PRD 정합성 감사 — 2026-10-21

사용자 요청 "지금까지 한 결과물에서 PRD에 어긋나는 건 없는지 확인해줘"에 대한 읽기 전용 감사 기록이다. 제품 코드·migration·배포·운영 DB·매칭 재실행·main 병합은 하지 않았다.

- 감사 기준: `origin/main` **43553f6**. 별도 작업트리 `/private/tmp/serentable-prd-audit`(detached HEAD, 수정 없음). 감사 후 병합된 PR #61은 `frontend/src/main.tsx`·`guide.tsx`·`style.css`·`e2e/*`만 바꾸므로 아래 결론의 대상 파일과 겹치지 않는다(현재 main `e401405`).
- PRD 원문: 로컬 PDF `docs/우연한 식탁_PRD.pdf`(v0.2) 추출 텍스트. 저장소에 원본·추출물을 추가하지 않았다.
- 대조 자료: `docs/adr/0002~0018`, `docs/design/mvp-implementation-spec.md`, `prd-kickoff-decisions.md`, `core-data-model.md`, 각 계약 문서.
- 분류: **편차**(PRD 문장과 다르고 승인 근거 없음) / **승인 예외**(ADR·U항목·P1/P2 범위) / **미검증**.
- 검증 방식: 전문 검토 3건(기능 ID, 어드민 화면·§16·§17, §13·§14)을 분담 실행하고, 지적마다 메인 에이전트가 해당 파일을 직접 열어 `파일:행` 근거를 재확인했다. 문서만 보고 "통과"로 표시하지 않았다.

## 1. 편차 (PRD 문장과 다르고 승인 근거 없음)

### 1.1 §14 알림 시나리오 11개 중 8개가 발송되지 않는다

PRD p.10 §14는 시점 11개를 제시한다: 신청 완료, 결제 대기, 결제 완료, 자동 재배치 중, 매칭 확정, 매칭 실패, 일정 이동 완료, 환불 요청·완료, 행사 1일 전, 행사 종료 후, 다음 모집 시작.

구현된 알림은 `CONFIRMED`·`VENUE_ASSIGNED`·`VENUE_PENDING`·`START_CONTENT`·`REMINDER`(모두 `backend/serentable/gatherings.py:323-330`의 `emit()`, 이벤트 키 `table:<table_id>:<event>`)와 `FEEDBACK_REMINDER`(`backend/serentable/feedback.py:210-244`)뿐이다. `enqueue_notification` 호출 지점은 전 저장소에서 이 두 곳이다.

없는 알림: 신청 완료, 결제 대기, 결제 완료, 자동 재배치 중, **매칭 실패**, 일정 이동 완료, 환불 요청·완료, 다음 모집 시작. 매칭 실패는 `ALTERNATIVE_OFFERED`로 저장되지만(`matching.py:673`) 알림이 없어 참가자는 화면을 다시 열어야 안다. 매칭 확정(INF-01)·1일 전 리마인드(INF-07)·종료 후 요청(§15)은 충족한다.

### 1.2 §11·§17 운영자 화면 일부가 없다

PRD §11 필수 화면 11개, §17 운영자 웹 10개 기준으로 확인했다.

| PRD 화면 | 상태 | 근거 |
|---|---|---|
| 운영 대시보드 | 있음 | `/admin/console`(`frontend/src/console.tsx`) |
| 회차 관리 | 있음 | `/admin/events` |
| 신청자 목록 | 있음(부분) | `/admin`(`main.tsx:632`) + `/admin/applications` |
| 자동 매칭 모니터 | 있음(부분) | `MatchHistory`(`applications.tsx:689`). 재배치 내역은 없음(1.4) |
| 예외 처리함 | 있음 | `exceptions.tsx` |
| **테이블 상세** | **없음** | `/admin/gathering-tables`(`gatherings.py:141-180`)는 테이블별 `food_snapshot`·`review_required`만 반환하고 참가자 구성·배정 식당명·단체방·안내 발송 상태를 포함하지 않는다 |
| 결제·환불 | 있음(부분) | 신청 목록에 결제 상태·환불 이력이 붙는다(`applications.tsx:313-388`). 별도 조회·필터 화면은 없음 |
| 참석 관리 | 있음(부분) | `/admin/safety`의 `NoShowSection`(노쇼 후보·판정). 사전/당일 취소 구분은 없음(1.3) |
| 피드백·안전 | 부분 | 신고 검토·제재는 있음(`safety.tsx`). **만족도 요약·개인별 비선호 검토 목록은 없다** — 운영자 화면의 피드백 정보는 대시보드 `피드백 제출률` 수치뿐이다 |
| **자동 메시지 관리** | **없음** | 템플릿·발송 이력 화면이 없음. `GET /api/admin/push-deliveries`(`notifications.py:179`)·`GET /api/admin/gathering-exceptions`(`:194`)는 있으나 `frontend/`에서 호출하는 곳이 없다. 대시보드의 `푸시 발송`(`dashboard.tsx:84`)은 회차별 집계일 뿐 이력이 아니다 |
| 식당 재고 관리 | 있음 | `/admin/venues` |

### 1.3 §11 대시보드 9개 지표 중 4개가 없거나 부분

| 지표 | 상태 | 근거 |
|---|---|---|
| 전체 신청자·결제 완료자 수 | 있음 | `dashboard.tsx:71-72` |
| 자동 매칭·재배치·확정 성공 건수와 성공률 | **부분** | 건수는 있음(`:73-77`). **성공률 계산·표시 없음**, **재배치 건수 없음**(1.4) |
| 대체 일정·환불 선택 대기자 수 | 있음 | `:78` |
| **자동 해결되지 않은 조건 충돌 건** | **없음** | 조건 충돌 지표가 대시보드에 없다. `열린 예외`(`:94`, `admin_dashboard.py:229-233`)는 식당 부족·환불 실패·대안 미응답·매칭 실패 합계다 |
| 자동 배정 가능 식당이 없는 테이블 | 있음 | `:79-82` |
| 안내·리마인드 자동 발송 실패 건 | 부분 | `:84` — 회차 키가 붙은 알림만 집계한다(`admin_dashboard.py:50-54`) |
| 자동 환불 실패 건 | 부분 | `failed_refund_count`(`admin_dashboard.py:136-143`)는 계산되지만 `열린 예외`에 합산되어 개별 표시가 없다 |
| 당일 취소·노쇼 후보 건 | 부분 | 노쇼 후보만 집계(`:85-89`). 당일 취소 상태가 없음(1.4) |
| 미처리 신고 건 | 있음 | `:93` |

### 1.4 §12 상태값이 4축 모두 PRD 값으로 저장되지 않는다

PRD §12는 "신청, 결제, 매칭, 참석 상태를 하나의 값으로 합치지 않고 분리해 저장한다"고 하고 축별 값을 나열한다.

- **결제:** `payment.state` CHECK는 `PENDING/PAID/FAILED/REFUNDED` 4개뿐이다(`migrations/versions/0006_payment.py:38`, `0010_match_resolution.py:51`). PRD의 `REFUND_AVAILABLE`은 파생 플래그(`applications.py:124-137,282`), `REFUND_REQUESTED/REFUND_PROCESSING/REFUND_FAILED`는 `mock_refund_event` 행(`0010:52-57`)으로만 존재한다. 참가자·운영자 화면에는 `refund_events`가 "환불 요청/처리 중/완료"로 표시되므로(§PAY-01 가시성 자체는 충족) 문제는 저장 모델이 PRD 문장과 1:1로 대응하지 않는다는 점이다.
- **매칭:** `MATCHING`·`REALLOCATING`은 enum에 예약만 되어 있고(`0007_matching.py:21-22`) 어떤 코드도 쓰지 않는다. `TRANSFERRED`는 저장값이 아니라 `match_resolution` 조회에서 `action == "TRANSFER"`로 파생된다(`match_resolution.py:183`). 실제로 쓰이는 값은 `WAITING/CONFIRMED/ALTERNATIVE_OFFERED/NO_MATCH/EXCEPTION`이다.
- **참석:** `attendance_check_in` 행과 `no_show_review`의 `CONFIRMED_NO_SHOW/EXCUSED`(`0012_feedback.py:14-24`)만 있고 `SCHEDULED/ATTENDED/CANCELED_EARLY/CANCELED_LATE/NO_SHOW` 상태값은 스키마에 없다. 노쇼 후보는 파생 목록이다(`attendance.py:87-101`).
- 신청 축(`DRAFT/SUBMITTED/CANCELED`)은 PRD와 일치한다(`0005_application.py:37`).

### 1.5 §16 "생성·분리·병합·재배치·확정 결과를 기록" 중 분리·병합·재배치 기록 없음

버전·기준·생성·확정은 기록된다(`match_run.algorithm_version/rule_version/policy/search_complete`, `dining_table`, `match_run_member`). 반면:

- **분리·병합(MAT-09):** DP가 처음부터 4~6인 그룹만 만든다(`matching.py:151-190`, `size == 0 or size >= MIN_TABLE_SIZE`). 지역 탐색의 이동 집합도 착석·새 테이블 개설·1인 이동·2인 교환·좌석 대체뿐이다(`:286-329`). `_borrow`는 원 테이블이 4명 미만이 되면 이동을 거부한다(`:370-377`) — 즉 "미완성 테이블 병합" 경로 자체가 없다. PRD가 상정하는 "7명 이상 후보군 분리"도 별도 단계가 아니며, 결과적으로 유효한 4~6인 테이블만 나온다. 분리·병합이 일어났는지를 남기는 기록도 없다.
- **재배치:** `REALLOCATING` 미기록(1.4), `table_assignment.ended_at`을 쓰는 재배치 경로가 없다. `matching.py:12`가 "reallocation across slots (①-c) is not done here"라고 명시한다.
- 운영자 화면의 `이전 만남 N명 · 동의한 대안 이동 N회`(`matching-explanations.tsx:33`)는 참가자 동의 `TRANSFER` 횟수이며 재배치 횟수가 아니다.

### 1.6 §7.2 "반드시 표시할 정보" 12항목 중 4항목 누락

| # | 항목 | 상태 |
|---|---|---|
| 1 | 테이블 인원수 | 있음(운영자·참가자) |
| 2 | **참가자별 희망 날짜·지역 충족 여부** | **없음** — 실행 기록·화면 모두에 항목이 없다 |
| 3 | 최고·최저 연령과 차이 | 부분 — 출생연도 범위만, 차이 수치 없음(`matching-explanations.tsx:21`) |
| 4·5·6 | 성비·MBTI 구성·공통 관심사 | 있음(운영자) |
| 7 | 만나고 싶은 사람 조건 충족 | 부분 — 성향별 충족 **%**만, 항목별 충족/미충족 판정 없음(`:32`) |
| 8 | 이전 만남 여부 | 부분 — 쌍 개수만 |
| 9 | **차단·비선호 충돌 여부** | **없음** — `participant_exclusion`은 매칭 입력 필터로만 쓰인다(`matching.py:711`) |
| 10 | 추천 점수·조건별 평가 | 있음(운영자) |
| 11 | **자동 재배치 횟수와 최종 배치 사유** | **없음** — 실행 이력에서 사유를 보이는 것은 미배정(`UNSEATED`) 구성원의 `reason_code`뿐(`applications.tsx:759-761`)이고, 참가자별 최종 배치 사유는 없다. 재배치 횟수 항목 자체가 없다 |
| 12 | 자동 확정 또는 매칭 실패 시각 | 부분 — `match_run.finished_at`은 API에 있으나(`matching.py:980`) UI가 렌더하지 않고, 테이블 확정 시각은 없다 |

참가자에게 상세 점수를 노출하지 않는다는 MAT-12는 위반되지 않았다(§7.2 뷰는 운영자 전용 `MatchHistory`에서만 렌더).

### 1.7 PAY-02 문구가 PRD 문장과 다르다

PRD PAY-02: "결제 전과 신청 완료 화면에서 **진행 2일 전 이후 환불 제한 및 당일 취소·노쇼 정책**을 확인할 수 있다."
구현 문구는 FAQ 현행 기준인 "화요일 24:00 이후 환불 불가"이고, 당일 취소·노쇼는 "정책 미정"으로 표시한다(`frontend/src/payments.tsx:51-58`, `:62-68`; 리마인드 본문도 동일: `gatherings.py` `reminder_body`). 노출 위치는 충족하지만 PRD가 요구한 규정 내용을 담지 않는다. 원인은 U04 미결정이며(FAQ 화요일 기준과 PRD "2일 전"의 관계: `prd-kickoff-decisions.md` C6), 정책 자체가 미확정이라는 점은 숨기지 않고 화면에 적고 있다.

### 1.8 대체 일정 목록이 참가자 선호로 좁혀지지 않는다 (STA-04 / §7.4)

PRD §7.4는 ①같은 날짜·같은 지역 → ②같은 날짜·다른 희망 지역 → ③다른 날짜·같은 지역 → ④다른 날짜·다른 지역 순으로 재배치를 시도하고, 없으면 ⑤미선택 회차를 추천하되 동의 후 이동하라고 한다. 구현의 대체 목록은 모집 중인 회차를 `ORDER BY s.starts_at, r.sort_order, s.id`로 전부 반환하며(`applications.py:242-256`), 참가자의 희망 날짜·지역을 필터·정렬에 쓰지 않는다(`target_allowed`, `match_resolution.py:158-173`은 마감·미확정 실행·중복 후보·시간 겹침만 본다). 실패 **이유**는 제시된다.

ADR-0012/U07은 "PRD §7.4 날짜·지역 **상대 우선순위**와의 차이는 명시적 MVP 예외"라고 적고 있으나, 그 예외 문장은 매칭 시각순(회차 경합)을 가리키는 맥락이고 대체 목록의 선호 정렬을 면제한다고 명시하지 않는다. 승인 범위가 불명확한 항목으로 남긴다.

### 1.9 "최초 신청 5분" 목표가 측정된 적 없다

PRD §16 사용성: "최초 신청은 프로필 입력을 포함해 5분 안에 완료할 수 있어야 한다." 저장소에서 이 목표를 측정한 기록·시험을 찾지 못했다. 미검증 항목이다(2.3).

## 2. 승인된 예외·범위 (편차 아님)

| 항목 | 근거 |
|---|---|
| MAT-04 우선순위를 사전식이 아닌 가중합으로 반영(MBTI·관심사 가중치가 낮아 뒤 항목이 결과를 더 좌우할 수 있음) | ADR-0011 §57, U05/U06 |
| §7.4 날짜·지역 상대 우선순위 대신 매칭 시각순 유지 | ADR-0012, U07 |
| 확정 후 취소·자동 충원·재배치 미구현(§15 "확정 후 1명 취소") | ADR-0018 U13 — STA-07·MAT-14 P1 미구현으로 확정 |
| 최소 점수·가중치 운영자 설정 UI 없음(MAT-15 P1, 회차별 값) | ADR-0011/U14 — 후속 |
| ACC-01 로그인이 테스트 계정(login_id/비밀번호)만 지원 | PRD가 "해커톤에서는 테스트 계정 로그인을 허용", ADR-0008 합성 계정 |
| P1/P2 미구현: ACC-06, MAT-14, MAT-15, MAT-16, CON-04, RET-03, STA-07, PAY-04 | `mvp-implementation-spec.md` 범위 |
| 신고 접수 즉시 당사자 분리 | ADR-0014 U09, PRD §15와 일치 |
| 만족도·노쇼를 매칭 점수에 미반영 | ADR-0014 U08 |
| 실제 PG·외부 식당 예약 API 없음(가상 재고) | ADR-0002, PRD PAY-04 P1 |

## 3. 미검증 (통과로 표시하지 않은 것)

- 배포 환경 4단계(해제·재배치)·8단계(대안·이동·환불): 로컬 격리 근거만. 운영 데이터에 실패 상태를 만들지 않기로 한 결정에 따른 것(`twelve-step-acceptance-matrix.md:47`).
- ~~배포 10단계 후기 리마인드·11단계 두 번째 회차: 미실행.~~ → 감사 이후 정정: 11단계는 2026-10-19 `check-matching --previous-slot-id` PASS, 10단계는 2026-10-21 운영 `check-feedback-reminder` PASS(`docs/operations/deployed-twelve-step-verification.md`).
- Android/Chrome 실기기 푸시, 권한 거부 경로: 미확인(iOS는 사용자 확인).
- 최초 신청 5분: 측정 기록 없음(1.9).
- Mac 호스트 Python→Docker PG 조합의 단일 전체 실행 1 FAIL 원인: 미확정(Linux 컨테이너 383 PASS와 구분).

## 4. 문서와 구현이 어긋난 곳 (제품 편차 아님)

- `docs/design/matching-contract.md:13` — "P0 미구현(후속): 대안 선택 실행(STA-05/06·PAY-03)과 회차 간 재배치(MAT-08)"라고 적혀 있으나 대안 선택 실행은 이미 구현되어 있다. 같은 문서 3행이 자기 서술이 계약 작성 시점 기록임을 밝히고 있다.
- `docs/operations/submission-readiness.md:5` — "열린 PR은 0건이며 main b633118이 운영에 배포" 서술이 현재(감사 후 main `e401405`)와 다르다. 같은 문서 7행이 이미 부분 정정을 달아 두었으나 1절 표는 낡은 값(b633118)을 유지한다.

## 5. 이번 감사에서 수행하지 않은 것

제품 코드·migration·seed·운영 DB·매칭 재실행·배포·main 병합을 하지 않았다. 감사는 `/private/tmp/serentable-prd-audit`(detached, 변경 0)에서 읽기만 했다. 사용자 미커밋 `AGENTS.md`·`docs/agents/HANDOFF.md`와 미추적 `.claude/`·`.codex/`·`scripts/claude-*.sh`는 보존했다.

## 6. 우선순위 제안 (사용자 결정 필요)

제출(2026-10-21 23:59) 전 판단이 필요한 순서:

1. **§14 필수 알림 8종 누락** — P0 요구이면서 결제·매칭 실패·환불 안내가 참가자에게 자동으로 가지 않는다. 최소한 매칭 실패와 결제 완료만이라도 알림을 붙일지.
2. **§11/§17 자동 메시지 관리·테이블 상세 화면** — 심사 시연에서 화면 목록과 대조될 수 있다.
3. **§12 상태값 저장 모델** — 화면 가시성은 충족하므로 문구·기록으로 설명할지, 결제 축을 확장할지.
4. **PAY-02 문구** — U04 미결정을 유지한 채 "PRD 요구는 미정 정책으로 대체"라고 명시할지.

나머지(1.5~1.9)는 ADR-0018로 확정된 범위와 겹치므로, 제출 문서에서 "구현하지 않은 P1/P2 및 승인 예외"로 명시하는 편이 안전하다.
## 7. 후속 조치 (2026-10-21, 사용자 승인)

| 항목 | 조치 | 근거 |
|---|---|---|
| 1.1 §14 알림 | 신청 완료·결제 대기, 결제 완료, 매칭 실패, 일정 이동 완료, 환불 완료·실패, 이용권 보관 알림 추가. 자동 재배치 중·다음 모집 시작은 보내지 않는 이유를 적음 | ADR-0019, `backend/serentable/participant_notices.py`, `tests/test_participant_notices.py` |
| 1.7 PAY-02 | PRD 문구로 변경. 화요일 24:00는 FAQ Q1이 답한 현행 "진행 2일 전" 시점. 당일 취소·노쇼는 확정된 동작으로 명시 | ADR-0019 |
| 1.8 대체 일정 | PRD §7.4 순서로 정렬하고 구분 표시. 목록에서 빼지는 않음 | ADR-0019, `applications.py` `preference_order` |
| 1.2 운영자 화면 | `/admin/messages` 「테이블·메시지」 추가. 테이블 상세(참가자·식당·예약명·단체방·안내 발송 상태)와 자동 메시지 종류(발송 시점·채널)·최근 발송 이력. 읽기 전용. 만족도 요약 화면은 추가하지 않음(대시보드 피드백 제출률과 CSV로 대신) | `admin_messages.py`, `messages.tsx`, `tests/test_admin_messages.py` |
| 1.3 대시보드 지표 | 매칭 성공률(성공 실행의 확정/전체), 식사 조건 충돌(재검토 대기), 자동 환불 실패를 따로 표시. 재배치 건수는 1.6의 참가자별 횟수로 대신하고, 당일 취소는 확정 후 앱 내 취소가 없어(ADR-0018) 노쇼 후보로 집계 | `admin_dashboard.py`, `dashboard.tsx` |
| 1.6 §7.2 표시 | 확정·실패 시각, 연령 차이, 차단·비선호·신고 충돌 없음(필수 조건), 희망 날짜·지역 충족, 자동 재배치 횟수(다른 동의 회차로 자동으로 넘어간 횟수, 새로 기록)와 최종 배치 사유를 운영자 매칭 이력에 추가 | `matching.py` `reallocation_count`, `matching-explanations.tsx` |
| 1.4 상태값 저장 | 바꾸지 않음. 화면·API는 PRD 상태(결제 대기·완료·실패·환불 가능·처리 중·완료 등)를 모두 보여 주며, 저장은 원장(결제 상태 + 환불 이벤트 행)과 파생으로 나눠 이력을 지움 없이 남기는 설계. 운영 데이터 migration 위험 대비 이득이 작음 | `core-data-model.md` |
| 1.5 분리·병합 기록 | 바꾸지 않음. 엔진이 처음부터 4~6인 유효 테이블만 만들어 "미완성 테이블 병합" 단계가 없음(설계상 차이). 회차 간 자동 이동은 1.6의 재배치 횟수로 기록 | `matching.py` |
| 1.9 최초 신청 5분 | 사람 기준 측정 기록 없음(미검증으로 유지). 제출 문서에 미측정으로 적음 | — |
