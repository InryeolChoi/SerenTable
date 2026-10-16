"""Which applications a slot's matching may seat (Issue #4 "미결제 제외 조건").

An application is matching-eligible for a slot when all of these hold:

- it is SUBMITTED and its candidate for that slot is live;
- it is paid, judged as of `least(now, slot.closes_at)`:
  - a PAID single-pass payment of that application completed by then, or
  - a PAID membership of the application's owner that started by then and expires after
    the slot starts (provisional U03 coverage).

Judging payment as of the slot close means a payment or membership completed after the
close never makes an application eligible retroactively. Payments for an application are
refused after its earliest candidate close, and the matching step must lock the slot row
FOR UPDATE and read the database clock before calling this (see application-contract.md).
"""

from sqlalchemy import text

# Columns used: c = application_candidate, a = application, s = event_slot.
ELIGIBLE = """c.live AND a.state = 'SUBMITTED' AND (
    EXISTS (
        SELECT 1 FROM payment p JOIN entitlement e ON e.payment_id = p.id
        WHERE p.application_id = a.id AND p.state = 'PAID' AND e.kind = 'SINGLE'
          AND p.completed_at <= least(:now, s.closes_at))
    OR EXISTS (
        SELECT 1 FROM entitlement e JOIN payment p ON p.id = e.payment_id
        WHERE e.user_id = a.user_id AND e.kind = 'MEMBERSHIP' AND p.state = 'PAID'
          AND e.starts_at <= least(:now, s.closes_at) AND e.expires_at > s.starts_at))"""

CANDIDATES = """FROM application_candidate c
    JOIN application a ON a.id = c.application_id
    JOIN event_slot s ON s.id = c.event_slot_id"""


def matching_eligible_applications(connection, slot_id, now):
    """Eligible applications for one slot, in submission order: [{application_id, user_id}].

    One participant may appear with several applications only for different slots; a slot
    is held by at most one live candidate per participant.
    """
    rows = connection.execute(
        text(f"""SELECT a.id AS application_id, a.user_id {CANDIDATES}
        WHERE c.event_slot_id = :slot_id AND {ELIGIBLE}
        ORDER BY a.submitted_at, a.id"""),
        {"slot_id": slot_id, "now": now},
    ).mappings()
    return [dict(row) for row in rows]


def eligible_slot_ids(connection, application_ids, now):
    """Application id -> ids of the candidate slots it is matching-eligible for."""
    eligible = {application_id: [] for application_id in application_ids}
    if not application_ids:
        return eligible
    for row in connection.execute(
        text(f"""SELECT c.application_id, c.event_slot_id {CANDIDATES}
        WHERE c.application_id = ANY(:ids) AND {ELIGIBLE}
        ORDER BY s.starts_at, s.id"""),
        {"ids": list(application_ids), "now": now},
    ).mappings():
        eligible[row["application_id"]].append(str(row["event_slot_id"]))
    return eligible
