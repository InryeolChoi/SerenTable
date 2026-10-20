"""PRD §14 participant notices outside the table lifecycle.

Each notice is written in the caller's transaction, so it exists exactly when the state
change it describes commits. Event keys are per object, and enqueue_notification is
idempotent on (user, event_key), so retries and replays never duplicate a notice.
Lock screens still show only the generic text from sw.js; the detail stays in the app.
"""

from sqlalchemy import text

from serentable.clock import SEOUL
from serentable.notifications import enqueue_notification

TITLE = "우연한 식탁 안내"
WEEKDAYS = "월화수목금토일"

FAILURE_REASONS = {
    "not_enough_eligible": "조건을 함께 충족하는 신청자가 4명보다 적었습니다",
    "capacity": "회차 정원이 모두 찼습니다",
    "unknown_age": "출생연도 정보가 없어 연령 조건을 확인할 수 없었습니다",
    "age_gap": "연령 차이 조건을 충족하는 테이블이 없었습니다",
    "no_valid_table": "필수 조건을 충족하는 테이블을 만들 수 없었습니다",
    "no_qualifying_table": "최소 매칭 점수를 충족하는 테이블이 없었습니다",
}


def when(moment):
    local = moment.astimezone(SEOUL)
    return f"{local.month}월 {local.day}일 ({WEEKDAYS[local.weekday()]}) {local:%H:%M}"


def _slot(connection, slot_id):
    return (
        connection.execute(
            text("""SELECT s.starts_at, s.matches_at, r.name AS region_name
            FROM event_slot s JOIN region r ON r.code=s.region_code WHERE s.id=:id"""),
            {"id": slot_id},
        )
        .mappings()
        .one()
    )


def _live_slots(connection, application_id):
    return (
        connection.execute(
            text("""SELECT min(s.closes_at) AS closes_at, min(s.matches_at) AS matches_at
            FROM application_candidate c JOIN event_slot s ON s.id=c.event_slot_id
            WHERE c.application_id=:id AND c.live"""),
            {"id": application_id},
        )
        .mappings()
        .one()
    )


def application_submitted(connection, user_id, application_id, now):
    slots = _live_slots(connection, application_id)
    deadline = (
        f"가장 이른 신청 마감({when(slots['closes_at'])})" if slots["closes_at"] else "신청 마감"
    )
    enqueue_notification(
        connection,
        user_id,
        f"application:{application_id}:submitted",
        "APPLICATION_SUBMITTED",
        TITLE,
        "신청이 완료되었습니다. 지금은 결제 대기 상태입니다. "
        f"{deadline} 전까지 내 식탁에서 이용권을 골라 모의 결제를 마쳐야 매칭 후보가 됩니다. "
        "신청 내용 확인과 취소도 마감 전까지 내 식탁에서 할 수 있습니다.",
        "/participant",
        now,
    )


def payment_completed(connection, user_id, application_id, payment_id, product, now):
    slots = _live_slots(connection, application_id)
    schedule = (
        f" 자동 매칭은 {when(slots['matches_at'])}에 실행될 예정입니다."
        if slots["matches_at"]
        else ""
    )
    enqueue_notification(
        connection,
        user_id,
        f"payment:{payment_id}:paid",
        "PAYMENT_COMPLETED",
        TITLE,
        f"모의 결제가 완료되었습니다({product['name']} {product['price_krw']:,}원, 실제 결제 없음)."
        + schedule,
        "/participant",
        now,
    )


def matching_failed(connection, user_id, application_id, run_id, reason, now):
    cause = FAILURE_REASONS.get(reason, "조건을 충족하는 테이블을 찾지 못했습니다")
    enqueue_notification(
        connection,
        user_id,
        f"match-failed:{run_id}:{application_id}",
        "MATCHING_FAILED",
        TITLE,
        f"이번 회차는 매칭되지 않았습니다. 사유: {cause}. "
        "내 식탁에서 신청 가능한 다른 날짜·지역으로 이동, 이용권 보관, 환불 중 하나를 "
        "선택해 주세요. 결제는 유지되며 선택 전까지 아무것도 자동으로 바뀌지 않습니다.",
        "/participant",
        now,
    )


def schedule_moved(connection, user_id, resolution_id, slot_id, now):
    slot = _slot(connection, slot_id)
    enqueue_notification(
        connection,
        user_id,
        f"resolution:{resolution_id}:moved",
        "SCHEDULE_MOVED",
        TITLE,
        f"일정 이동이 완료되었습니다. 새 회차: {when(slot['starts_at'])} · "
        f"{slot['region_name']}. 기존 결제를 그대로 사용하며, 자동 매칭은 "
        f"{when(slot['matches_at'])}에 실행될 예정입니다.",
        "/participant",
        now,
    )


def pass_held(connection, user_id, resolution_id, single, now):
    enqueue_notification(
        connection,
        user_id,
        f"resolution:{resolution_id}:held",
        "PASS_HELD",
        TITLE,
        "이용권을 보관했습니다. 다음 신청에서 다시 사용할 수 있습니다."
        if single
        else "멤버십 기간을 유지한 채 이번 신청을 마쳤습니다. 다음 회차에 다시 신청할 수 있습니다.",
        "/participant",
        now,
    )


def refund_finished(connection, user_id, resolution_id, attempt, now):
    if attempt["state"] == "SUCCEEDED":
        key, kind = f"refund:{resolution_id}:completed", "REFUND_COMPLETED"
        body = (
            f"환불이 완료되었습니다. 원결제 금액 {attempt['amount_krw']:,}원 전액 모의 환불 "
            "(요청 → 처리 → 완료). 실제 입출금은 없습니다."
        )
    else:
        key, kind = f"refund:{resolution_id}:failed", "REFUND_FAILED"
        body = (
            f"환불 요청({attempt['amount_krw']:,}원)을 접수했지만 처리 중 문제가 생겼습니다. "
            "운영자가 다시 처리하며, 그동안 이용권은 예약 상태로 보존됩니다."
        )
    enqueue_notification(connection, user_id, key, kind, TITLE, body, "/participant", now)
