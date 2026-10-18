"""Work #8 attendance: participant check-in and operator no-show review (FDB-01, U15)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_operator,
    require_csrf_participant,
    require_operator,
)
from serentable.database import database_engine

router = APIRouter()

# The live confirmed seat of one user at one table. Locking the assignment row serializes
# a check-in against a no-show review of the same seat.
SEAT = """SELECT s.starts_at-interval '30 minutes' AS opens_at,s.ends_at,
      clock_timestamp() AS now
    FROM table_assignment a
    JOIN match_participation mp ON mp.application_id=a.application_id
      AND mp.user_id=a.user_id AND mp.dining_table_id=a.dining_table_id
      AND mp.state='CONFIRMED'
    JOIN dining_table t ON t.id=a.dining_table_id
    JOIN event_slot s ON s.id=t.event_slot_id
    WHERE a.dining_table_id=:table_id AND a.user_id=:user_id AND a.ended_at IS NULL
    FOR UPDATE OF a"""


def lock_seat(connection, table_id, user_id):
    return (
        connection.execute(text(SEAT), {"table_id": table_id, "user_id": user_id})
        .mappings()
        .first()
    )


def check_in_json(row):
    return {
        "table_id": str(row["dining_table_id"]),
        "checked_in_at": row["checked_in_at"].isoformat(),
    }


@router.post("/api/me/tables/{table_id}/check-in")
def check_in(table_id: uuid.UUID, user: Principal = Depends(require_csrf_participant)):
    params = {"table_id": table_id, "user_id": user.id}
    created = False
    with database_engine().begin() as connection:
        seat = lock_seat(connection, table_id, user.id)
        if not seat:
            raise HTTPException(404, "table_not_found")
        row = (
            connection.execute(
                text("""SELECT dining_table_id,checked_in_at FROM attendance_check_in
                WHERE dining_table_id=:table_id AND user_id=:user_id"""),
                params,
            )
            .mappings()
            .first()
        )
        if not row:
            if not seat["opens_at"] <= seat["now"] <= seat["ends_at"]:
                raise HTTPException(409, "check_in_closed")
            row = (
                connection.execute(
                    text("""INSERT INTO attendance_check_in(dining_table_id,user_id,checked_in_at)
                    VALUES(:table_id,:user_id,:now) RETURNING dining_table_id,checked_in_at"""),
                    {**params, "now": seat["now"]},
                )
                .mappings()
                .one()
            )
            created = True
        result = check_in_json(row)
    response = private_response({"check_in": result})
    response.status_code = 201 if created else 200
    return response


CANDIDATES = """SELECT a.dining_table_id,a.user_id,s.starts_at,s.ends_at,r.name AS region_name,
    p.data->>'display_name' AS display_name
    FROM table_assignment a
    JOIN match_participation mp ON mp.application_id=a.application_id
      AND mp.user_id=a.user_id AND mp.dining_table_id=a.dining_table_id
      AND mp.state='CONFIRMED'
    JOIN dining_table t ON t.id=a.dining_table_id
    JOIN event_slot s ON s.id=t.event_slot_id
    JOIN region r ON r.code=s.region_code
    LEFT JOIN participant_profile p ON p.user_id=a.user_id
    WHERE a.ended_at IS NULL AND s.ends_at < clock_timestamp()
      AND NOT EXISTS(SELECT 1 FROM attendance_check_in c
        WHERE c.dining_table_id=a.dining_table_id AND c.user_id=a.user_id)
      AND NOT EXISTS(SELECT 1 FROM no_show_review n
        WHERE n.dining_table_id=a.dining_table_id AND n.user_id=a.user_id)"""


@router.get("/api/admin/no-show-candidates")
def no_show_candidates(operator: Principal = Depends(require_operator)):
    with database_engine().connect() as connection:
        rows = connection.execute(
            text(CANDIDATES + " ORDER BY s.ends_at,a.dining_table_id,a.user_id")
        ).mappings()
        result = [
            {
                "table_id": str(row["dining_table_id"]),
                "user_id": str(row["user_id"]),
                "display_name": row["display_name"] or "참가자",
                "region_name": row["region_name"],
                "starts_at": row["starts_at"].isoformat(),
                "ends_at": row["ends_at"].isoformat(),
            }
            for row in rows
        ]
    return private_response({"candidates": result})


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["CONFIRMED_NO_SHOW", "EXCUSED"]


REVIEW_COLUMNS = "dining_table_id,user_id,decision,reviewed_at"


def review_json(row):
    return {
        "table_id": str(row["dining_table_id"]),
        "user_id": str(row["user_id"]),
        "decision": row["decision"],
        "reviewed_at": row["reviewed_at"].isoformat(),
    }


@router.post("/api/admin/no-show-candidates/{table_id}/{user_id}")
def review_no_show(
    table_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ReviewInput,
    operator: Principal = Depends(require_csrf_operator),
):
    params = {"table_id": table_id, "user_id": user_id}
    created = False
    with database_engine().begin() as connection:
        seat = lock_seat(connection, table_id, user_id)
        if not seat:
            raise HTTPException(404, "candidate_not_found")
        row = (
            connection.execute(
                text(f"""SELECT {REVIEW_COLUMNS} FROM no_show_review
                WHERE dining_table_id=:table_id AND user_id=:user_id"""),
                params,
            )
            .mappings()
            .first()
        )
        if row:
            if row["decision"] != payload.decision:
                raise HTTPException(409, "no_show_already_reviewed")
        else:
            candidate = connection.execute(
                text(CANDIDATES + " AND a.dining_table_id=:table_id AND a.user_id=:user_id"),
                params,
            ).first()
            if not candidate:
                raise HTTPException(404, "candidate_not_found")
            row = (
                connection.execute(
                    text(f"""INSERT INTO no_show_review
                    (dining_table_id,user_id,decision,reviewed_by,reviewed_at)
                    VALUES(:table_id,:user_id,:decision,:operator,clock_timestamp())
                    RETURNING {REVIEW_COLUMNS}"""),
                    {**params, "decision": payload.decision, "operator": operator.id},
                )
                .mappings()
                .one()
            )
            created = True
        result = review_json(row)
    response = private_response({"review": result})
    response.status_code = 201 if created else 200
    return response
