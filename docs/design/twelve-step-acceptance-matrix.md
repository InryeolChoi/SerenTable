# PRD 12단계 E2E 인수 근거 매트릭스

- 작성: 2026-10-19, Work #10 「12단계 E2E·100명·복구 검증」의 12단계 부분
- 기준: [구현 명세 §4](./mvp-implementation-spec.md#4-prd-12단계-e2e-인수-기준), ADR-0011~0015, [용어집](../../GLOSSARY.md)
- 기준 브랜치: `codex/work7-gathering-integration`(b5f1525) 위 `claude/w10-twelve-step`

## 읽는 법과 경계

- **로컬 자동 근거**: 격리 로컬 PostgreSQL + FastAPI HTTP(`TestClient`) + 매칭·안내 실행기. 아래에서 "별도 프로세스"는 `python -m serentable.worker --once`를 subprocess로 실행한 시험이고, 나머지는 같은 프로세스에서 `run_due_matches()`·`run_gathering_jobs()`를 직접 호출한다. 시각 이동은 격리 회차의 시각만 SQL로 바꾸는 시험 고정 장치이며 제품 시계 덮어쓰기가 아니다.
- **브라우저 근거**: `frontend/e2e/*.spec.ts`(Playwright, 모바일 에뮬레이션). 이번 작업에서는 다시 실행하지 않았다(포트 공유). 기존 기록의 통과 결과를 인용하며 현재 브랜치에서 재실행 대상이다.
- **배포·실기기 근거**: 이 문서의 어떤 항목도 배포 환경 통과를 뜻하지 않는다. Work7~9 기능은 HANDOFF 기준 **운영 미반영**이며, 명세 §4는 "배포 환경에서 확인할 결과"를 요구하므로 12단계 인수는 전 단계 **미완료**다.
- 체인 시험: `tests/test_twelve_step_flow.py::test_one_slot_runs_all_twelve_steps_without_operator_action_after_the_deadline` (이하 **체인**). 한 회차의 1→2→3→5→6→7→9→10→11→12 정상 흐름을 별도 프로세스 실행기로 연결하고, 마감 후 운영자 감사 기록이 없음과 미해결 예외 0건을 끝에서 확인한다. 8단계는 정상 흐름이 아니므로 체인에 넣지 않았다.

## 단계별 근거

| 단계 | 로컬 자동 근거 (path::test) | 증명하는 것 | 공백·한계 |
|---|---|---|---|
| 1 신청 | `tests/test_applications.py::test_participant_submits_explicit_candidates_and_sees_own_status`, `::test_submission_requires_complete_profile_consents_and_recruiting_candidates`, `::test_concurrent_submits_create_exactly_one_application`; `tests/test_payments.py::test_single_pass_payment_snapshots_product_and_holds_pass_for_the_application`; 체인; 브라우저 `frontend/e2e/applications.spec.ts`, `payments.spec.ts`, `events.spec.ts` | 프로필·동의 완료자만 날짜·지역 후보를 명시 선택해 신청, 멱등·동시 제출 1건, 모의 결제 | 체인의 4명은 같은 프로필 내용(계정만 다름). 서로 다른 프로필은 `matching.spec.ts`(출생연도 상이)·`test_matching_scale.py`(합성 100명)에서 확인 |
| 2 마감·결제자만 | `tests/test_matching_runner.py::test_unpaid_and_too_few_applications_are_left_out_with_a_reason`, `::test_matching_does_not_run_before_the_matching_time`, `::test_a_slot_runs_once_and_a_repeated_cycle_does_not_run_it_again`, `::test_only_one_concurrent_runner_seats_a_slot`; `tests/test_failure_and_duplicates.py::test_only_paid_or_membership_covered_applications_are_matching_eligible`, `::test_payment_after_the_earliest_candidate_close_is_refused`; 체인(미결제 1명 제외) | 매칭 시각 전 미실행, 결제 완료·멤버십 적용 신청만 대상, 회차당 1회·동시 실행 1개 | 실제 운영 스케줄(10초 루프) 상 정시성은 배포 환경 확인 필요 |
| 3 4~6인·우선순위 | `tests/test_matching_runner.py::test_the_planner_seats_as_many_as_the_oracle_and_never_breaks_a_hard_constraint`, `::test_thirteen_compatible_people_are_not_lost_to_greedy_table_sizes`, `::test_the_run_records_policy_and_table_scores_for_the_operator_only`; `tests/test_matching_plan.py` 전체; `tests/test_matching_score.py`; `tests/oracle/`; `tests/test_matching_scale.py::test_a_separate_worker_confirms_100_paid_applicants_without_hard_violations`; 체인 | H1~H7 위반 0(독립 정답 비교), 점수 손계산 일치, 최소 점수 60 이상 테이블만, 100명 별도 프로세스 | 목적함수 전역 최적은 보장하지 않음(ADR-0011 §5). 가중치의 실제 만족도 타당성은 검증 불가 |
| 4 해제·재배치 | `tests/test_matching_plan.py::test_a_table_below_the_minimum_score_is_not_built`, `::test_an_excluded_pair_never_shares_a_table_and_everyone_is_still_seated`, `::test_swaps_group_shared_interests_when_the_seat_count_is_equal`; `tests/test_recommendations.py::test_the_next_matching_separates_excluded_pairs_and_spares_mutual_meet_again`(실제 PG, 제외 쌍을 분리해 8명 전원 재착석); **신규** `tests/test_twelve_step_flow.py::test_the_worker_dissolves_a_table_below_the_minimum_score_into_alternative_offers`(별도 프로세스) | 최소 점수 미달 조합은 확정되지 않고 `ALTERNATIVE_OFFERED`·`no_qualifying_table`, 권리 HELD 유지·대안 조회 가능. 제외 관계 위반 조합은 수리 후 다른 테이블로 재착석 | 재배치는 **같은 회차 실행 안의** 수리·교환이다. 확정 후 취소 충원/재배치(U13)는 미결정·미구현. PRD §7.4 날짜·지역 상대 우선순위는 승인된 MVP 예외(ADR-0012, 매칭 시각순) |
| 5 자동 확정 | `tests/test_matching_runner.py::test_four_paid_applications_are_seated_at_one_table_and_reported_over_http`, `::test_confirmation_uses_the_single_pass_once_and_retries_keep_its_usage_time`, `::test_a_database_failure_rolls_back_all_confirmations_and_rights_before_retry`, `::test_a_participant_is_never_confirmed_at_two_tables_at_the_same_time`; 체인; 브라우저 `matching.spec.ts` | 운영자 시작·승인 경로 없이 확정, 1회권 1회 사용, DB 실패 시 전체 롤백 후 재시도 | — |
| 6 식당·단체방 | `tests/test_gatherings.py::test_unknown_food_is_an_exception_then_verified_inventory_allocates_once`, `::test_worker_reminders_start_content_and_rollback_are_atomic`; `tests/test_chat.py` 전체; 체인 | 가격대·정원·음식 조건 충족 재고 1회 배정, 미확인은 예외, 방 생성·확정 멤버만 접근, 저장 장애 시 원자적 롤백 | 실제 식당 예약 API 없음(ADR-0002 가상 재고) |
| 7 결과·안내 확인 | `tests/test_matching_runner.py::test_four_paid_applications_are_seated_at_one_table_and_reported_over_http`(최소 소개만 노출); `tests/test_chat.py::test_messages_persist_and_reconnect_without_duplicates_or_private_fields`; 체인(방 메시지·알림·연락처/Instagram/점수 비노출); 브라우저 `matching.spec.ts`, `zz-feedback-console.spec.ts`(방 메시지 송신·새로고침) | 참가자가 확정·식당·예약명·안내 메시지를 방과 화면에서 확인, 비공개 정보 미노출 | "큐레이션"은 시작 시각 이후 자동 게시되는 대화 주제(9단계). 실제 휴대폰 화면 확인은 배포 환경 필요 |
| 8 미매칭 대안·이동/환불·보관 | `tests/test_matching_resolution.py::test_alternative_selection_keeps_payment_and_reaches_worker_confirmation`, `::test_hold_and_reuse_never_rewrite_purchase_and_need_no_new_payment`, `::test_system_failure_refund_is_full_mock_and_repeat_safe`, `::test_membership_extends_once_at_final_failure_and_cash_refund_is_deferred`, `::test_two_simultaneous_choices_have_one_winner_and_identical_replays_are_stable`, `::test_resolution_rolls_back_every_change_after_database_failure`; `tests/test_matching_alternatives.py`; `tests/test_mock_refund_retry.py`; 브라우저 `matching.spec.ts`(이동·보관·환불), `zzz-refund-recovery.spec.ts` | 동일 신청 이동 후 실행기 확정, 보관 1회권 재사용(추가 결제 없음), 전액 모의 환불·멱등, 멤버십 +7일 1회, 실패 시 운영자 재시도 | 실제 PG·멤버십 금액 환불·일반 취소는 범위 밖·미정(U03/U04) |
| 9 리마인드·행사 중 콘텐츠 | `tests/test_gatherings.py::test_worker_reminders_start_content_and_rollback_are_atomic`(별도 프로세스 2개 동시); `tests/test_notifications.py::test_three_attempts_one_and_five_minutes_then_single_operator_exception`, `::test_encrypted_provider_acceptance_and_duplicate_dispatch`, `::test_unconfigured_and_expired_are_unavailable_without_retry`; 체인 | 24시간 이내 리마인드·시작 후 대화 주제 각 1회 게시, 반복 실행 중복 없음, 종료 후 소급 게시 없음, 푸시 3회 시도 후 운영자 예외 | **실기기 푸시 수신 미검증**: 가짜 공급자 성공은 실기기 수신이 아니다(ADR-0013). 시험 실행기는 VAPID 미설정이라 푸시는 UNAVAILABLE |
| 10 체크인·만족도·사람별 선호 | `tests/test_attendance.py` 전체; `tests/test_feedback.py::test_feedback_opens_only_after_the_end_and_can_be_revised`, `::test_avoid_records_the_exclusion_atomically_and_stays_private`, `::test_unanswered_members_get_exactly_one_reminder_after_a_day`; `tests/test_safety.py`; 체인; 브라우저 `zz-feedback-console.spec.ts` | 시작 30분 전~종료 체크인(U15 승인 기준), 종료 후 평가·수정, 사람별 선호 비공개 저장, 미응답 1회 리마인드, 노쇼 후보는 운영자 확인 후 확정 | 위치 기반 도착 확인은 없음(앱 버튼 체크인) |
| 11 다음 매칭 반영 | `tests/test_recommendations.py::test_the_next_matching_separates_excluded_pairs_and_spares_mutual_meet_again`, `::test_recommendations_put_well_rated_then_attended_places_first`, `::test_recommendations_follow_active_sanctions_without_penalizing_warnings`; 체인(`new` 16.67 = 6쌍 중 상호 재만남 1쌍 제외 5쌍 기존 만남) | 이전 만남은 새로운 사람 점수 감점, 상호 재만남 쌍은 면제, 비선호·차단·신고는 필수 제외, 평가 기반 회차 추천 | 만족도·노쇼는 점수 미반영(U08 승인). 반영 효과의 실제 만족도 개선은 검증 불가 |
| 12 정상 흐름 무개입·미해결 예외만 어드민 | **체인**(마감 후 운영자 감사 0건, `/api/admin/exceptions?state=OPEN` 빈 목록, 노쇼 후보 0, 두 회차 대시보드 예외 0); `tests/test_admin_exceptions.py` 전체(식당 부족·대안 미응답만 예외로 표시, 처리 기록·감사); `tests/test_admin_dashboard.py::test_worker_results_show_matching_venue_room_push_and_exception_counts`, `::test_exhausted_push_retries_count_as_open_exceptions_of_their_table_slot`; `tests/test_operator_recovery.py`; 브라우저 `zz-feedback-console.spec.ts` | 정상 흐름은 운영자 조작 없이 끝나고, 예외(식당 미확인·푸시 소진·대안 미응답·환불 실패)만 운영자 목록에 남는다 | 운영자의 사전 작업(회차·식당 재고 등록)은 마감 전 준비로 본다. 배포 환경에서 심사위원 계정으로 재현 필요 |

## 이번에 추가한 시험

| 시험 | 메우는 공백 |
|---|---|
| `tests/test_twelve_step_flow.py::test_one_slot_runs_all_twelve_steps_without_operator_action_after_the_deadline` | 단계별 시험은 있었으나 한 회차에서 1→12를 **연결**하고 끝에서 "미해결 예외 0·마감 후 운영자 조작 0"을 확인하는 API 경계 시험이 없었다 |
| `tests/test_twelve_step_flow.py::test_the_worker_dissolves_a_table_below_the_minimum_score_into_alternative_offers` | 최소 점수 미달 해제가 계획 함수(DB 없음) 수준에서만 확인됐다. 실제 PG·별도 프로세스 실행기·HTTP에서 `no_qualifying_table`, 권리 유지, 대안 조회, 예외 미생성을 확인 |

결과(2026-10-19, 로컬 PostgreSQL 컨테이너 `127.0.0.1:55432`, 전용 DB `serentable_w10_a`): `uv run pytest -q tests/test_twelve_step_flow.py` 2 passed(23.3초). 제품 결함은 발견되지 않았다. 이 결과는 로컬 격리 근거이며 배포 환경 통과가 아니다.

통합 브랜치 `claude/w10-acceptance`(ccf1469, 리뷰 반영: 실제 마감 여유를 회차 생성 시점부터 10~15초로 넓히고 추가 합성 계정을 시험 후 삭제)에서 전용 DB `serentable_w10_int` 기준:

- 전체 `uv run pytest -q`: **320 passed (815.99초)**. 잠자기 방지(`caffeinate`) 없이 돌린 첫 실행은 기계가 잠자기에 들어가 마감 시각 시험 40 FAIL·11 ERROR가 났고 frontend 빌드도 없었다. 원인이 환경이므로 제품 결함으로 세지 않으며, 같은 코드 재실행 320 PASS로 확인했다.
- 브라우저 E2E(Node 26, 포트 8000 비어 있음 확인): **10 passed / 2 failed**. 실패 2개(`zz-feedback-console`, `zzz-refund-recovery`)는 시험 고정 장치의 DB 이름 허용 목록(`serentable_test` 등) 검사에서 멈췄고 제품 화면 단계까지 가지 않았다. 기존 보존 DB를 건드리지 않기 위해 허용된 이름으로 재실행하지 않았다. 이 두 시험은 **이번 브랜치에서 미검증**이며 CI 또는 허용된 전용 DB에서 재실행이 필요하다(이번 브랜치는 frontend·backend 제품 코드를 바꾸지 않았다).

## 남은 공백

- **배포 환경 12단계 미완료**: Work7~9 migration·deploy가 승인 전이라 공개 URL에서 전 단계를 재현하지 못했다. 심사위원용 참가자·운영자 계정·링크 제공과 결과 안내까지 접속 유지도 미확인. 배포 후 사용자가 실행할 단계별 검증 도구와 절차는 [배포 환경 12단계 검증 절차](../operations/deployed-twelve-step-verification.md)에 있다(로컬 실행만 확인, 운영 미실행).
- **실기기 푸시 미완료**: 실제 휴대폰 구독·수신(권한 허용/거부·미지원 포함)은 별도 인수.
- **브라우저 E2E 재실행**: 이번 작업에서 Playwright를 실행하지 않았다. 현재 브랜치에서 재실행이 필요하다.
- **같은 회차 내 재배치의 별도 프로세스 근거**: 제외 관계 수리·재착석은 실제 PG지만 같은 프로세스 실행기 호출(`test_recommendations.py`)로만 확인된다.
- **실제 실행기 강제 종료 복구**: PR #35(worker crash) 범위이며 이 문서에서 다루지 않는다.

## 미결정 정책 (구현하지 않음)

- U16 감사·신고·개인정보 보관 기간과 삭제 정책.
- 운영자 세부 역할 분리(현재 단일 `operator` 역할).
- 기존 운영 조치 전반의 사유 입력 필수화(현재는 예외 처리 메모 등 일부 조치만 사유를 받는다).
- U13 확정 후 취소 충원/재배치, U04 일반 취소·부분 환불, 멤버십 금액 환불.
