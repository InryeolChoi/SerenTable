"""Work #8 private table feedback and per-person preferences (feedback-contract.md T2)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_participant,
    require_participant,
)
from serentable.database import database_engine

router = APIRouter()

RATING_FIELDS = (
    "table_rating",
    "conversation_rating",
    "venue_rating",
    "rejoin_intent",
    "recommend_intent",
)

# A confirmed, still-held seat at the table (contract 공통 규칙).
SEATED = """SELECT ta.user_id FROM table_assignment ta
    JOIN match_participation mp ON mp.application_id=ta.application_id
      AND mp.user_id=ta.user_id AND mp.dining_table_id=ta.dining_table_id
      AND mp.state='CONFIRMED'
    WHERE ta.dining_table_id=:table_id AND ta.ended_at IS NULL"""


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_rating: int = Field(strict=True, ge=1, le=5)
    conversation_rating: int = Field(strict=True, ge=1, le=5)
    venue_rating: int = Field(strict=True, ge=1, le=5)
    rejoin_intent: int = Field(strict=True, ge=1, le=5)
    recommend_intent: int = Field(strict=True, ge=1, le=5)


def authorize(connection, table_id, user_id):
    """Return whether the table has ended; 404 for anyone without a confirmed seat."""
    ended = connection.execute(
        text(
            """SELECT s.ends_at<=clock_timestamp() FROM dining_table t
            JOIN event_slot s ON s.id=t.event_slot_id
            WHERE t.id=:table_id AND :user_id IN ("""
            + SEATED
            + ")"
        ),
        {"table_id": table_id, "user_id": user_id},
    ).first()
    if ended is None:
        raise HTTPException(404, "table_not_found")
    return ended[0]


def require_ended(connection, table_id, user_id):
    if not authorize(connection, table_id, user_id):
        raise HTTPException(409, "feedback_not_open")


def state(connection, table_id, user_id):
    ended = authorize(connection, table_id, user_id)
    feedback = (
        connection.execute(
            text(
                "SELECT "
                + ",".join(RATING_FIELDS)
                + " FROM table_feedback WHERE dining_table_id=:table_id AND user_id=:user_id"
            ),
            {"table_id": table_id, "user_id": user_id},
        )
        .mappings()
        .first()
    )
    # Only the rater's own choices are ever joined; nobody sees choices about themselves.
    mates = connection.execute(
        text(
            """SELECT seat.user_id,COALESCE(p.data->>'display_name','참가자') AS display_name,
            pref.choice FROM ("""
            + SEATED
            + """) seat
            LEFT JOIN participant_profile p ON p.user_id=seat.user_id
            LEFT JOIN person_preference pref ON pref.dining_table_id=:table_id
              AND pref.rater_id=:user_id AND pref.target_id=seat.user_id
            WHERE seat.user_id<>:user_id ORDER BY display_name,seat.user_id"""
        ),
        {"table_id": table_id, "user_id": user_id},
    ).mappings()
    return {
        "table_id": str(table_id),
        "open": ended,
        "feedback": dict(feedback) if feedback else None,
        "tablemates": [
            {
                "user_id": str(row["user_id"]),
                "display_name": row["display_name"],
                "preference": row["choice"],
            }
            for row in mates
        ],
    }


@router.get("/api/me/tables/{table_id}/feedback")
def get_feedback(table_id: uuid.UUID, user: Principal = Depends(require_participant)):
    with database_engine().connect() as connection:
        return private_response(state(connection, table_id, user.id))


@router.put("/api/me/tables/{table_id}/feedback")
def put_feedback(
    table_id: uuid.UUID,
    payload: FeedbackInput,
    user: Principal = Depends(require_csrf_participant),
):
    with database_engine().begin() as connection:
        require_ended(connection, table_id, user.id)
        columns = ",".join(RATING_FIELDS)
        connection.execute(
            text(
                f"""INSERT INTO table_feedback(dining_table_id,user_id,{columns},submitted_at)
                VALUES(:table_id,:user_id,"""
                + ",".join(f":{name}" for name in RATING_FIELDS)
                + """,clock_timestamp())
                ON CONFLICT(dining_table_id,user_id) DO UPDATE SET """
                + ",".join(f"{name}=EXCLUDED.{name}" for name in RATING_FIELDS)
                + ",submitted_at=EXCLUDED.submitted_at"
            ),
            {"table_id": table_id, "user_id": user.id, **payload.model_dump()},
        )
        return private_response(state(connection, table_id, user.id))


class PreferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: uuid.UUID
    choice: Literal["MEET_AGAIN", "AVOID"] | None


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferences: list[PreferenceItem] = Field(min_length=1, max_length=20)


@router.put("/api/me/tables/{table_id}/preferences")
def put_preferences(
    table_id: uuid.UUID,
    payload: PreferencesInput,
    user: Principal = Depends(require_csrf_participant),
):
    from serentable.safety import record_exclusion

    targets = [item.target_id for item in payload.preferences]
    if len(set(targets)) != len(targets):
        raise HTTPException(422, "duplicate_target")
    with database_engine().begin() as connection:
        require_ended(connection, table_id, user.id)
        mates = set(
            connection.execute(
                text(SEATED + " AND ta.user_id<>:user_id"),
                {"table_id": table_id, "user_id": user.id},
            ).scalars()
        )
        if not set(targets) <= mates:
            raise HTTPException(422, "target_not_tablemate")
        for item in payload.preferences:
            params = {"table_id": table_id, "rater": user.id, "target": item.target_id}
            if item.choice is None:
                # Clearing never lifts an exclusion already recorded (safety first).
                connection.execute(
                    text("""DELETE FROM person_preference WHERE dining_table_id=:table_id
                    AND rater_id=:rater AND target_id=:target"""),
                    params,
                )
                continue
            connection.execute(
                text("""INSERT INTO person_preference
                (dining_table_id,rater_id,target_id,choice,updated_at)
                VALUES(:table_id,:rater,:target,:choice,clock_timestamp())
                ON CONFLICT(dining_table_id,rater_id,target_id) DO UPDATE
                SET choice=EXCLUDED.choice,updated_at=EXCLUDED.updated_at
                WHERE person_preference.choice<>EXCLUDED.choice"""),
                {**params, "choice": item.choice},
            )
            if item.choice == "AVOID":
                record_exclusion(connection, user.id, item.target_id, "avoid")
        return private_response(state(connection, table_id, user.id))


REMINDER_KEY = "feedback-reminder:{table}"


def run_feedback_jobs():
    """Remind each seated member once when feedback is still missing a day after the end.

    The 24-hour delay is the implementation default. Tables that ended more than 7 days ago
    are skipped so a first deployment never sends retroactive reminders. The unique
    (user_id, event_key) notification keeps concurrent or repeated runs to a single reminder.
    """
    from serentable.notifications import enqueue_notification

    with database_engine().begin() as connection:
        due = (
            connection.execute(
                text("""SELECT ta.dining_table_id,ta.user_id,clock_timestamp() AS now
            FROM table_assignment ta
            JOIN match_participation mp ON mp.application_id=ta.application_id
              AND mp.user_id=ta.user_id AND mp.dining_table_id=ta.dining_table_id
              AND mp.state='CONFIRMED'
            JOIN dining_table t ON t.id=ta.dining_table_id
            JOIN event_slot s ON s.id=t.event_slot_id
            WHERE ta.ended_at IS NULL
              AND s.ends_at<=clock_timestamp()-interval '24 hours'
              AND s.ends_at>clock_timestamp()-interval '7 days'
              AND NOT EXISTS(SELECT 1 FROM table_feedback f
                WHERE f.dining_table_id=ta.dining_table_id AND f.user_id=ta.user_id)
              AND NOT EXISTS(SELECT 1 FROM app_notification n WHERE n.user_id=ta.user_id
                AND n.event_key='feedback-reminder:'||ta.dining_table_id::text)
            ORDER BY ta.dining_table_id,ta.user_id""")
            )
            .mappings()
            .all()
        )
        for row in due:
            enqueue_notification(
                connection,
                row["user_id"],
                REMINDER_KEY.format(table=row["dining_table_id"]),
                "FEEDBACK_REMINDER",
                "우연한 식탁 모임 후기",
                "지난 모임은 어떠셨나요? 참가 이력에서 비공개 평가를 남겨 주세요. "
                "평가는 다른 참가자에게 공개되지 않으며, 남기지 않아도 다음 신청은 가능합니다.",
                "/participant/history",
                row["now"],
            )
