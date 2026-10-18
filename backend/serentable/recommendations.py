"""Work #8 participant history and next-slot recommendations (feedback-contract.md T4)."""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from serentable.auth import Principal, private_response, require_participant
from serentable.clock import SEOUL
from serentable.database import database_engine
from serentable.events import SLOT_COLUMNS, slot_json
from serentable.safety import participation_restricted

router = APIRouter()

# The caller's own confirmed seats (contract 공통 규칙) with only the caller's own flags.
# Windows follow T1 (start-30min..end) and T2 (after the end) by the database clock.
HISTORY = """SELECT a.dining_table_id,s.id AS event_slot_id,s.region_code,
      r.name AS region_name,s.starts_at,s.ends_at,
      EXISTS(SELECT 1 FROM attendance_check_in c
        WHERE c.dining_table_id=a.dining_table_id AND c.user_id=a.user_id) AS checked_in,
      EXISTS(SELECT 1 FROM table_feedback f
        WHERE f.dining_table_id=a.dining_table_id AND f.user_id=a.user_id)
        AS feedback_submitted,
      clock_timestamp() BETWEEN s.starts_at-interval '30 minutes' AND s.ends_at
        AS check_in_open,
      s.ends_at<=clock_timestamp() AS feedback_open
    FROM table_assignment a
    JOIN match_participation mp ON mp.application_id=a.application_id
      AND mp.user_id=a.user_id AND mp.dining_table_id=a.dining_table_id
      AND mp.state='CONFIRMED'
    JOIN dining_table t ON t.id=a.dining_table_id
    JOIN event_slot s ON s.id=t.event_slot_id
    JOIN region r ON r.code=s.region_code
    WHERE a.user_id=:user_id AND a.ended_at IS NULL
    ORDER BY s.starts_at DESC,a.dining_table_id"""


def history_json(row):
    starts = row["starts_at"].astimezone(SEOUL)
    return {
        "table_id": str(row["dining_table_id"]),
        "event_slot_id": str(row["event_slot_id"]),
        "region": {"code": row["region_code"], "name": row["region_name"]},
        "date": starts.date().isoformat(),
        "starts_at": starts.isoformat(),
        "ends_at": row["ends_at"].astimezone(SEOUL).isoformat(),
        **{
            name: row[name]
            for name in ("checked_in", "feedback_submitted", "check_in_open", "feedback_open")
        },
    }


@router.get("/api/me/history")
def get_history(user: Principal = Depends(require_participant)):
    with database_engine().connect() as connection:
        rows = connection.execute(text(HISTORY), {"user_id": user.id}).mappings().all()
    return private_response({"tables": [history_json(row) for row in rows]})


# ISO weekday (1=Monday) of a timestamp in Seoul.
WEEKDAY = "extract(isodow from {} AT TIME ZONE 'Asia/Seoul')::int"

# Rank 1: a region and weekday whose own table ratings average 4 or more.
# Rank 2: a region where the caller checked in. Rank 3: everything else still recruiting.
# Slots with a live candidate of the caller are already applied to and left out. Missing
# feedback only means fewer rank-1 places; it never hides a slot (FDB-04).
RECOMMENDATIONS = f"""WITH seats AS (
      SELECT a.dining_table_id,a.user_id,s.region_code,
        {WEEKDAY.format("s.starts_at")} AS weekday
      FROM table_assignment a
      JOIN match_participation mp ON mp.application_id=a.application_id
        AND mp.user_id=a.user_id AND mp.dining_table_id=a.dining_table_id
        AND mp.state='CONFIRMED'
      JOIN dining_table t ON t.id=a.dining_table_id
      JOIN event_slot s ON s.id=t.event_slot_id
      WHERE a.user_id=:user_id AND a.ended_at IS NULL),
    liked AS (
      SELECT seats.region_code,seats.weekday FROM seats
      JOIN table_feedback f ON f.dining_table_id=seats.dining_table_id
        AND f.user_id=seats.user_id
      GROUP BY seats.region_code,seats.weekday HAVING avg(f.table_rating)>=4),
    attended AS (
      SELECT DISTINCT seats.region_code FROM seats
      JOIN attendance_check_in c ON c.dining_table_id=seats.dining_table_id
        AND c.user_id=seats.user_id)
    SELECT {SLOT_COLUMNS},{WEEKDAY.format("s.starts_at")} AS weekday,
      CASE WHEN EXISTS(SELECT 1 FROM liked l WHERE l.region_code=s.region_code
          AND l.weekday={WEEKDAY.format("s.starts_at")}) THEN 1
        WHEN EXISTS(SELECT 1 FROM attended d WHERE d.region_code=s.region_code) THEN 2
        ELSE 3 END AS rank
    FROM event_slot s JOIN region r ON r.code=s.region_code
    WHERE s.closes_at>:now
      AND NOT EXISTS(SELECT 1 FROM application_candidate c
        WHERE c.user_id=:user_id AND c.live AND c.event_slot_id=s.id)
      AND NOT EXISTS(SELECT 1 FROM match_participation mp
        JOIN event_slot confirmed ON confirmed.id=mp.event_slot_id
        WHERE mp.user_id=:user_id AND mp.state='CONFIRMED'
          AND confirmed.starts_at<s.ends_at AND s.starts_at<confirmed.ends_at)
    ORDER BY rank,s.starts_at,r.sort_order"""

WEEKDAY_NAMES = ("월", "화", "수", "목", "금", "토", "일")


def reason(row):
    region = row["region_name"]
    if row["rank"] == 1:
        return f"지난 {region} {WEEKDAY_NAMES[row['weekday'] - 1]}요일 모임을 높게 평가하셨어요."
    if row["rank"] == 2:
        return f"참석하셨던 {region} 지역의 모임이에요."
    return "모집 중인 가까운 일정이에요."


@router.get("/api/me/recommendations")
def get_recommendations(user: Principal = Depends(require_participant)):
    with database_engine().connect() as connection:
        now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        if participation_restricted(connection, user.id, now):
            return private_response({"recommendations": []})
        rows = (
            connection.execute(text(RECOMMENDATIONS), {"user_id": user.id, "now": now})
            .mappings()
            .all()
        )
    return private_response(
        {
            "recommendations": [
                {"event_slot": slot_json(row, now), "reason": reason(row)} for row in rows
            ]
        }
    )
