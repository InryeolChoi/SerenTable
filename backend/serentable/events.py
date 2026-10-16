"""Recruitment slots: operators define them, participants see the ones still open."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_operator,
    require_operator,
    require_participant,
)
from serentable.database import database_engine

router = APIRouter()
# Korea observes no daylight saving time, so a fixed offset is exact for display.
SEOUL = timezone(timedelta(hours=9))


class EventSlotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_code: str = Field(min_length=1, max_length=32)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    closes_at: AwareDatetime
    matches_at: AwareDatetime
    capacity: int = Field(strict=True, ge=4, le=100)

    @model_validator(mode="after")
    def time_order(self):
        if not self.starts_at < self.ends_at:
            raise ValueError("ends_before_start")
        if not self.closes_at <= self.matches_at <= self.starts_at:
            raise ValueError("close_match_start_order")
        return self


SLOT_COLUMNS = """s.id, s.region_code, r.name AS region_name, s.starts_at, s.ends_at,
    s.closes_at, s.matches_at, s.capacity"""


def slot_json(row, now):
    return {
        "id": str(row["id"]),
        "region": {"code": row["region_code"], "name": row["region_name"]},
        **{
            name: row[name].astimezone(SEOUL).isoformat()
            for name in ("starts_at", "ends_at", "closes_at", "matches_at")
        },
        "capacity": row["capacity"],
        "recruiting": row["closes_at"] > now,
    }


def field_error(field, kind):
    return RequestValidationError([{"type": kind, "loc": ("body", field), "msg": kind}])


@router.get("/api/admin/regions")
def list_regions(operator: Principal = Depends(require_operator)):
    try:
        with database_engine().connect() as connection:
            rows = connection.execute(
                text("SELECT code, name FROM region ORDER BY sort_order")
            ).mappings()
            return private_response({"regions": [dict(row) for row in rows]})
    except SQLAlchemyError:
        raise HTTPException(503, "event_slot_unavailable") from None


@router.post("/api/admin/event-slots")
def create_event_slot(
    payload: EventSlotInput, operator: Principal = Depends(require_csrf_operator)
):
    now = datetime.now(timezone.utc)
    if payload.closes_at <= now:
        raise field_error("closes_at", "closes_in_past")
    slot_id = uuid.uuid4()
    try:
        with database_engine().begin() as connection:
            if not connection.execute(
                text("SELECT 1 FROM region WHERE code=:code"), {"code": payload.region_code}
            ).scalar():
                raise field_error("region_code", "region_unknown")
            connection.execute(
                text("""INSERT INTO event_slot
                (id, region_code, starts_at, ends_at, closes_at, matches_at, capacity, created_by)
                VALUES (:id, :region_code, :starts_at, :ends_at, :closes_at, :matches_at,
                        :capacity, :created_by)"""),
                {"id": slot_id, "created_by": operator.id, **payload.model_dump()},
            )
            row = (
                connection.execute(
                    text(f"""SELECT {SLOT_COLUMNS} FROM event_slot s
                    JOIN region r ON r.code = s.region_code WHERE s.id = :id"""),
                    {"id": slot_id},
                )
                .mappings()
                .one()
            )
    except IntegrityError as error:
        # The unique (region, start) constraint also settles concurrent duplicate submits.
        if getattr(getattr(error.orig, "diag", None), "constraint_name", "") == (
            "event_slot_region_start"
        ):
            raise HTTPException(409, "event_slot_duplicate") from None
        raise HTTPException(503, "event_slot_unavailable") from None
    except SQLAlchemyError:
        raise HTTPException(503, "event_slot_unavailable") from None
    response = private_response({"event_slot": slot_json(row, now)})
    response.status_code = 201
    return response


def read_slots(where, now):
    try:
        with database_engine().connect() as connection:
            rows = (
                connection.execute(
                    text(f"""SELECT {SLOT_COLUMNS} FROM event_slot s
                    JOIN region r ON r.code = s.region_code {where}
                    ORDER BY s.starts_at, r.sort_order"""),
                    {"now": now},
                )
                .mappings()
                .all()
            )
    except SQLAlchemyError:
        raise HTTPException(503, "event_slot_unavailable") from None
    return private_response({"event_slots": [slot_json(row, now) for row in rows]})


@router.get("/api/admin/event-slots")
def list_all_event_slots(operator: Principal = Depends(require_operator)):
    return read_slots("", datetime.now(timezone.utc))


@router.get("/api/event-slots")
def list_open_event_slots(user: Principal = Depends(require_participant)):
    return read_slots("WHERE s.closes_at > :now", datetime.now(timezone.utc))
