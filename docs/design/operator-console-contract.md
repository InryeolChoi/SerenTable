# Work #9 운영자 예외·안전 종합 관리 계약

Issue #9가 기준이다. 근거 요구는 [구현 명세](mvp-implementation-spec.md) 운영자 스토리 44~54와 PRD §11·§16이다. 통합 브랜치는 `claude/work9-operator-console`이고 기반은 Work #8 통합 브랜치다. 스키마는 `0013_operator_audit`(T0)다.

## 원칙 (PRD에서 그대로 옴)

- **승인 관문 없음:** 어드민은 정상 흐름의 수동 승인 관문이 아니다. 새 화면은 조회와 예외 처리만 하며, 정상 흐름에 승인 단계를 추가하지 않는다.
- **권한:** 모든 `/api/admin/*`는 `require_operator`로 막고, 쓰기 API는 `require_csrf_operator`를 쓴다. 참가자 요청은 403이다.
- **감사:** 운영자의 주요 변경은 `serentable.audit.record_audit(connection, actor, action, target_type, target_id, reason=, before=, after=)`로 **같은 트랜잭션**에 기록한다. 변경이 롤백되면 감사 행도 남지 않는다. 기록 항목은 변경 주체·시각·원인·이전/이후 상태다.
- **개인정보:** 감사·대시보드·CSV에 연락처·Instagram·신고 상세 원문·비밀값을 넣지 않는다(ADR-0008). 참가자는 표시명과 내부 id로만 식별한다.

## 시험 경계(seam)와 PRD 적합성

사용자 지시(2026-10-18): PRD 등 지침에 어긋나지 않는 경계는 통과로 확정하고, 어긋나거나 근거가 없는 것은 "재확인 필요"로 남긴다.

| 경계 | 검증 내용 | 근거 | 판정 |
|---|---|---|---|
| 운영자 HTTP API + 실제 PostgreSQL | 조회 결과·권한 403·CSRF | 명세 46~53, AGENTS 검증 원칙 | 통과 |
| 별도 worker 실행 후 조회 | 자동 처리 결과가 대시보드·예외에 반영됨 | PRD §7.3, 명세 54 | 통과 |
| `record_audit` 트랜잭션 원자성 | 변경과 감사가 함께 커밋·롤백 | PRD §16 | 통과 |
| CSV 응답 본문 | 열·행 정답 비교, 수식 주입 방지 | PRD §16 | 통과 |
| 감사 보관 기간·삭제 | — | U16 후속 미정 | **재확인 필요**: 구현하지 않음 |
| 운영자 세부 권한(역할 분리) | — | PRD에 역할 구분 없음, 현재 operator 단일 역할 | **재확인 필요**: 단일 역할 유지 |

## 티켓 그래프

각 티켓은 자기 파일만 소유한다. 라우터·화면 경로는 T0에 이미 등록돼 있으므로 `main.py`·`main.tsx`·migrations는 수정하지 않는다.

| 티켓 | 소유 파일 | 차단 |
|---|---|---|
| A 운영 대시보드 | `backend/serentable/admin_dashboard.py`, `frontend/src/dashboard.tsx`, `tests/test_admin_dashboard.py` | T0 |
| B 예외 통합 처리 | `backend/serentable/admin_exceptions.py`, `frontend/src/exceptions.tsx`, `tests/test_admin_exceptions.py` | T0 |
| C 감사 기록 연결·조회 | `backend/serentable/audit.py`(조회 API 추가, `record_audit` 시그니처 유지), `frontend/src/audit.tsx`, `tests/test_operator_audit.py`. 기존 운영자 쓰기 API에 `record_audit` 호출을 한 줄씩 추가한다: `events.py`, `gatherings.py`, `attendance.py`, `safety.py` | T0 |
| D CSV 내보내기 | `backend/serentable/exports.py`, `frontend/src/exports.tsx`, `tests/test_exports.py` | T0 |

### A 운영 대시보드 (명세 46, PRD §11)

- `GET /api/admin/dashboard?event_slot_id=` (생략하면 전체)는 회차별 집계를 돌려준다.
  - 신청 상태별 수, 결제 상태별 수
  - 매칭 실행 상태와 확정 인원·테이블 수, 대안 대기(`ALTERNATIVE_OFFERED`) 수
  - 식당 배정 완료/대기 수, 단체방 수
  - 푸시 발송 상태별 수
  - 체크인 수·노쇼 후보 수·피드백 제출률
  - 미처리 신고 수, 열린 예외 수
- 숫자만 돌려주고 개인 식별 정보는 없다.

### B 예외 통합 처리 (명세 48·49, MAT-13·PAY-03·INF-08)

- `GET /api/admin/exceptions?state=OPEN`은 처리할 예외를 한 목록으로 돌려준다. 각 항목에 종류·회차·원인 코드·발생 시각·상태가 있다.
  - `gathering_exception`(식당 부족, 발송 반복 실패)
  - 모의 환불 실패(`FAILED`)
  - 실패한 원래 회차 시작 이후에도 해결 선택이 남은 신청(2026-10-19 승인). 표시 기준이며 참가자 권한 만료가 아니다.
- `POST /api/admin/exceptions/{kind}/{id}/resolve`는 `{note}`(1~500자)를 받아 처리 결과를 기록한다.
  - `gathering_exception`은 `RESOLVED`와 `resolution_note`·`resolved_by`를 저장한다.
  - 같은 요청을 다시 보내도 결과는 같다.
  - `record_audit`를 같은 트랜잭션에서 기록한다.
- 처리는 기록만 하며 정상 흐름을 재실행하거나 승인하지 않는다.

### C 감사 기록 연결·조회 (명세 52, PRD §16)

- 기존 운영자 쓰기 API에 감사 기록을 연결한다.
  - 회차 생성
  - 식당 재고 등록, 음식 적합성 확인
  - 노쇼 판정
  - 신고 검토, 제재 기록
- `GET /api/admin/audit?target_type=&target_id=&limit=`는 최신순으로 돌려준다. 행위자는 표시명 대신 로그인 id만 보인다.
- 각 쓰기를 실패 주입으로 롤백하면 감사 행도 남지 않아야 한다.

### D CSV 내보내기 (명세 53, PRD §16)

- `GET /api/admin/exports/applications.csv?event_slot_id=`: 신청 id·표시명·신청 상태·결제 상태·매칭 상태·제출 시각
- `GET /api/admin/exports/tables.csv?event_slot_id=`: 테이블 id·점수·인원·표시명 목록·식당명·체크인 수
- 두 CSV 모두 UTF-8 BOM과 `Content-Disposition`을 붙인다.
- `=`,`+`,`-`,`@`로 시작하는 셀은 앞에 `'`를 붙여 수식 주입을 막는다.
- 연락처·Instagram은 넣지 않는다.
- 내보내기 자체를 `record_audit`(`export`)로 기록한다.

## 검증

- 티켓마다 TDD로 진행하고, 자기 격리 DB `serentable_w9_<티켓>`을 쓴다.
- 기대값은 독립 출처(손으로 만든 소규모 데이터의 직접 계산)로 정한다.
- Playwright는 통합 후 메인이 실행한다.
- 운영 DB·원본·보존 데모 DB는 사용하지 않는다.

## 2026-10-19 승인된 복구 범위

[ADR-0015](../adr/0015-operator-failure-recovery.md)에 따라 모의 환불 실패 기록과 운영자 멱등 재시도를 추가한다. 원결제 전액·미사용 1회권 범위를 유지하며 실제 PG·임의 실패 버튼·멤버십 금액 환불은 추가하지 않는다. 실패한 환불에 예약된 권리는 보존하고 다른 신청이나 매칭에 중복 사용하지 못하게 한다. DB 전체 장애는 실패 기록이 가능하다고 가정하지 않으며 전체 롤백과 오류로 응답한다. 감사 보관·운영자 역할 분리·기존 조치 전반의 사유 필수화는 계속 미정이다.
