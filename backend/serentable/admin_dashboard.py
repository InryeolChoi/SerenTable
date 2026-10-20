"""Work #9 A: read-only operator dashboard, counts per event slot (spec 46, PRD §11).

Counts only: no display names, user ids, login ids, contacts or report details leave this
module. Nothing here starts, approves or edits the normal flow.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from serentable.attendance import CANDIDATES
from serentable.auth import Principal, private_response, require_operator
from serentable.database import database_engine
from serentable.events import SLOT_COLUMNS, slot_json
from serentable.matching_exceptions import MATCHING_FAILURE_SELECT

router = APIRouter()

# Every per-slot query filters with this; a NULL parameter means all slots.
SLOT_FILTER = "(CAST(:slot AS uuid) IS NULL OR {0}=CAST(:slot AS uuid))"

APPLICATION_STATES = ("DRAFT", "SUBMITTED", "CANCELED")
PAYMENT_STATES = ("PENDING", "PAID", "FAILED", "REFUNDED")
PUSH_STATES = ("PENDING", "SENT", "FAILED", "UNAVAILABLE")

# An application counts toward every slot it named as a candidate, live or not, so a
# canceled application (whose candidates are no longer live) still shows as CANCELED.
APPLICATION_SLOTS = """SELECT DISTINCT c.application_id,c.event_slot_id
    FROM application_candidate c"""

# Tables that still hold a confirmed seat (same rule as gatherings and attendance).
LIVE_TABLES = """SELECT DISTINCT t.id,t.event_slot_id FROM dining_table t
    JOIN table_assignment ta ON ta.dining_table_id=t.id AND ta.ended_at IS NULL
    JOIN match_participation mp ON mp.application_id=ta.application_id
      AND mp.dining_table_id=t.id AND mp.state='CONFIRMED'"""

# Confirmed, still-held seats of tables whose slot has ended: who may leave feedback.
ENDED_SEATS = """SELECT t.event_slot_id,ta.dining_table_id,ta.user_id FROM table_assignment ta
    JOIN match_participation mp ON mp.application_id=ta.application_id
      AND mp.user_id=ta.user_id AND mp.dining_table_id=ta.dining_table_id
      AND mp.state='CONFIRMED'
    JOIN dining_table t ON t.id=ta.dining_table_id
    JOIN event_slot s ON s.id=t.event_slot_id
    WHERE ta.ended_at IS NULL AND s.ends_at<=clock_timestamp()"""

# Notifications carry no slot column; table events are keyed 'table:<id>:<event>' and
# 'feedback-reminder:<id>' (gatherings.emit, feedback.run_feedback_jobs). Others stay
# unattributed to any slot.
NOTIFICATION_SLOT = """SELECT n.id AS notification_id,t.event_slot_id FROM app_notification n
    JOIN dining_table t ON t.id::text=split_part(n.event_key,':',2)
    WHERE n.event_key LIKE 'table:%' OR n.event_key LIKE 'feedback-reminder:%'"""

# name -> (states, query); each query yields (slot id, state, count) rows.
STATE_QUERIES = {
    "applications": (
        APPLICATION_STATES,
        f"""SELECT c.event_slot_id,a.state,count(*) FROM ({APPLICATION_SLOTS}) c
        JOIN application a ON a.id=c.application_id
        WHERE {SLOT_FILTER.format("c.event_slot_id")} GROUP BY 1,2""",
    ),
    "payments": (
        PAYMENT_STATES,
        f"""SELECT c.event_slot_id,p.state,count(*) FROM ({APPLICATION_SLOTS}) c
        JOIN payment p ON p.application_id=c.application_id
        WHERE {SLOT_FILTER.format("c.event_slot_id")} GROUP BY 1,2""",
    ),
    "push": (
        PUSH_STATES,
        f"""SELECT ns.event_slot_id,d.state,count(*) FROM push_delivery d
        JOIN ({NOTIFICATION_SLOT}) ns ON ns.notification_id=d.notification_id
        WHERE {SLOT_FILTER.format("ns.event_slot_id")} GROUP BY 1,2""",
    ),
}

# name -> (slot column, query with a {0} slot filter); each yields (slot id, count) rows.
COUNT_QUERIES = {
    "matching_failure_count": (
        "m.event_slot_id",
        f"""SELECT m.event_slot_id,count(*) FROM ({MATCHING_FAILURE_SELECT}) m
        WHERE {{0}} GROUP BY 1""",
    ),
    "confirmed_count": (
        "mp.event_slot_id",
        """SELECT mp.event_slot_id,count(*) FROM match_participation mp
        WHERE mp.state='CONFIRMED' AND {0} GROUP BY 1""",
    ),
    # Unseated applications point at their run, not at a slot.
    "alternative_offered_count": (
        "r.event_slot_id",
        """SELECT r.event_slot_id,count(*) FROM match_participation mp
        JOIN match_run r ON r.id=mp.match_run_id
        WHERE mp.state='ALTERNATIVE_OFFERED' AND {0} GROUP BY 1""",
    ),
    "table_count": (
        "lt.event_slot_id",
        f"SELECT lt.event_slot_id,count(*) FROM ({LIVE_TABLES}) lt WHERE {{0}} GROUP BY 1",
    ),
    "venue_assigned": (
        "lt.event_slot_id",
        f"""SELECT lt.event_slot_id,count(*) FROM ({LIVE_TABLES}) lt
        JOIN venue_allocation va ON va.dining_table_id=lt.id WHERE {{0}} GROUP BY 1""",
    ),
    "room_count": (
        "lt.event_slot_id",
        f"""SELECT lt.event_slot_id,count(*) FROM ({LIVE_TABLES}) lt
        JOIN chat_room c ON c.dining_table_id=lt.id WHERE {{0}} GROUP BY 1""",
    ),
    "check_in_count": (
        "t.event_slot_id",
        """SELECT t.event_slot_id,count(*) FROM attendance_check_in c
        JOIN dining_table t ON t.id=c.dining_table_id WHERE {0} GROUP BY 1""",
    ),
    # Exactly the operator's no-show review queue (attendance.CANDIDATES).
    "no_show_candidate_count": (
        "t.event_slot_id",
        f"""SELECT t.event_slot_id,count(*) FROM ({CANDIDATES}) q
        JOIN dining_table t ON t.id=q.dining_table_id WHERE {{0}} GROUP BY 1""",
    ),
    "feedback_eligible": (
        "e.event_slot_id",
        f"SELECT e.event_slot_id,count(*) FROM ({ENDED_SEATS}) e WHERE {{0}} GROUP BY 1",
    ),
    "feedback_submitted": (
        "e.event_slot_id",
        f"""SELECT e.event_slot_id,count(*) FROM ({ENDED_SEATS}) e
        JOIN table_feedback f ON f.dining_table_id=e.dining_table_id AND f.user_id=e.user_id
        WHERE {{0}} GROUP BY 1""",
    ),
    "open_report_count": (
        "t.event_slot_id",
        """SELECT t.event_slot_id,count(*) FROM safety_report r
        JOIN dining_table t ON t.id=r.dining_table_id WHERE r.state='OPEN' AND {0} GROUP BY 1""",
    ),
    # Venue exceptions name their table; push exceptions are keyed 'push:<delivery id>'.
    "failed_refund_count": (
        "m.event_slot_id",
        """SELECT m.event_slot_id,count(*) FROM match_resolution r
        JOIN match_run m ON m.id=r.failure_run_id
        JOIN mock_refund_attempt a ON a.resolution_id=r.id
        WHERE r.action='REFUND' AND a.state='FAILED'
        AND a.attempt_number=(SELECT max(last.attempt_number) FROM mock_refund_attempt last
            WHERE last.resolution_id=r.id) AND {0} GROUP BY 1""",
    ),
    "alternative_overdue_count": (
        "m.event_slot_id",
        """SELECT m.event_slot_id,count(*) FROM match_participation mp
        JOIN application a ON a.id=mp.application_id JOIN match_run m ON m.id=mp.match_run_id
        JOIN event_slot s ON s.id=m.event_slot_id
        WHERE mp.state='ALTERNATIVE_OFFERED' AND a.state='SUBMITTED'
        AND s.starts_at<=clock_timestamp() AND {0} GROUP BY 1""",
    ),
    "open_exception_count": (
        "COALESCE(t.event_slot_id,ns.event_slot_id)",
        f"""SELECT COALESCE(t.event_slot_id,ns.event_slot_id),count(*)
        FROM gathering_exception e
        LEFT JOIN dining_table t ON t.id=e.dining_table_id
        LEFT JOIN push_delivery d ON 'push:'||d.id::text=e.event_key
        LEFT JOIN ({NOTIFICATION_SLOT}) ns ON ns.notification_id=d.notification_id
        WHERE e.state='OPEN' AND {{0}} GROUP BY 1""",
    ),
}

LATEST_RUN = f"""SELECT DISTINCT ON (event_slot_id) event_slot_id,state,attempt FROM match_run
    WHERE {SLOT_FILTER.format("event_slot_id")} ORDER BY event_slot_id,attempt DESC"""


def slot_rows(connection, slot):
    return (
        connection.execute(
            text(
                f"""SELECT {SLOT_COLUMNS} FROM event_slot s JOIN region r ON r.code=s.region_code
                WHERE {SLOT_FILTER.format("s.id")} ORDER BY s.starts_at DESC,s.id"""
            ),
            {"slot": slot},
        )
        .mappings()
        .all()
    )


def state_counts(connection, slot):
    sections = {}
    for name, (states, query) in STATE_QUERIES.items():
        counts = sections[name] = {}
        for slot_id, key, count in connection.execute(text(query), {"slot": slot}):
            counts.setdefault(slot_id, dict.fromkeys(states, 0))[key] = count
    return sections


def plain_counts(connection, slot):
    return {
        name: dict(
            connection.execute(text(query.format(SLOT_FILTER.format(column))), {"slot": slot}).all()
        )
        for name, (column, query) in COUNT_QUERIES.items()
    }


def slot_summary(slot, now, sections, counts, run):
    count = {name: values.get(slot["id"], 0) for name, values in counts.items()}
    eligible, submitted = count["feedback_eligible"], count["feedback_submitted"]
    return {
        "event_slot": slot_json(slot, now),
        **{
            name: values.get(slot["id"], dict.fromkeys(STATE_QUERIES[name][0], 0))
            for name, values in sections.items()
        },
        "matching": {
            "run_state": run["state"] if run else None,
            "attempt": run["attempt"] if run else None,
            "confirmed_count": count["confirmed_count"],
            "table_count": count["table_count"],
            "alternative_offered_count": count["alternative_offered_count"],
        },
        "gathering": {
            "venue_assigned": count["venue_assigned"],
            "venue_pending": count["table_count"] - count["venue_assigned"],
            "room_count": count["room_count"],
        },
        "attendance": {
            "check_in_count": count["check_in_count"],
            "no_show_candidate_count": count["no_show_candidate_count"],
            "feedback_submitted": submitted,
            "feedback_eligible": eligible,
            "feedback_rate": round(submitted / eligible, 4) if eligible else None,
        },
        "open_report_count": count["open_report_count"],
        "open_exception_count": (
            count["open_exception_count"]
            + count["failed_refund_count"]
            + count["alternative_overdue_count"]
            + count["matching_failure_count"]
        ),
    }


@router.get("/api/admin/dashboard")
def dashboard(
    event_slot_id: uuid.UUID | None = None, operator: Principal = Depends(require_operator)
):
    # One read-only REPEATABLE READ snapshot so every count describes the same moment.
    with database_engine().connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        slots = slot_rows(connection, event_slot_id)
        if event_slot_id and not slots:
            raise HTTPException(404, "event_slot_not_found")
        sections = state_counts(connection, event_slot_id)
        counts = plain_counts(connection, event_slot_id)
        runs = {
            row["event_slot_id"]: row
            for row in connection.execute(text(LATEST_RUN), {"slot": event_slot_id}).mappings()
        }
        result = [slot_summary(slot, now, sections, counts, runs.get(slot["id"])) for slot in slots]
    return private_response({"slots": result})
