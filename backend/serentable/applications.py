"""Participant applications: one submission over explicitly chosen recruiting slots."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_participant,
    require_operator,
    require_participant,
)
from serentable.clock import iso, locked_now
from serentable.database import database_engine
from serentable.eligibility import eligible_slot_ids
from serentable.events import SLOT_COLUMNS, field_error, slot_json
from serentable.matching import participation_details
from serentable.payments import payment_details
from serentable.profile import consent_state, profile_state, read_profile

router = APIRouter()


class ApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    event_slot_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)

    @field_validator("event_slot_ids")
    @classmethod
    def distinct(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("event_slot_ids_duplicate")
        return values


APPLICATION_COLUMNS = "a.id, a.user_id, a.state, a.submitted_at, a.canceled_at, a.created_at"


def applications_json(connection, rows, now, with_participant=False):
    """Attach each application's candidate slots, ordered by start time."""
    ids = [row["id"] for row in rows]
    candidates = {}
    if ids:
        for slot in connection.execute(
            text(f"""SELECT c.application_id, {SLOT_COLUMNS}
            FROM application_candidate c
            JOIN event_slot s ON s.id = c.event_slot_id
            JOIN region r ON r.code = s.region_code
            WHERE c.application_id = ANY(:ids) ORDER BY s.starts_at, r.sort_order"""),
            {"ids": ids},
        ).mappings():
            candidates.setdefault(slot["application_id"], []).append(slot_json(slot, now))
    payments = payment_details(connection, rows, now)
    eligible = eligible_slot_ids(connection, ids, now)
    matching = participation_details(connection, ids)
    return [
        {
            "id": str(row["id"]),
            "state": row["state"],
            "submitted_at": iso(row["submitted_at"]),
            "canceled_at": iso(row["canceled_at"]),
            "candidates": candidates.get(row["id"], []),
            "matching_eligible_slot_ids": eligible[row["id"]],
            # The stored matching axis, or null when no run has reached this application
            # yet; the screen then derives "waiting" from eligibility as before.
            "matching": matching[row["id"]],
        }
        | payments[row["id"]]
        | (
            {"participant": {"id": str(row["user_id"]), "login_id": row["login_id"]}}
            if with_participant
            else {}
        )
        for row in rows
    ]


def read_applications(connection, where, params, now, with_participant=False):
    rows = (
        connection.execute(
            text(f"""SELECT {APPLICATION_COLUMNS}, u.login_id FROM application a
            JOIN app_user u ON u.id = a.user_id {where}
            ORDER BY a.created_at DESC, a.id"""),
            params,
        )
        .mappings()
        .all()
    )
    return applications_json(connection, rows, now, with_participant)


def latest_consent_ids(connection, user_id):
    rows = connection.execute(
        text("""SELECT DISTINCT ON (purpose) purpose, id
        FROM consent_record WHERE user_id = :id ORDER BY purpose, id DESC"""),
        {"id": user_id},
    ).mappings()
    return {row["purpose"]: row["id"] for row in rows}


@router.get("/api/me/applications/{application_id}/alternatives")
def list_application_alternatives(
    application_id: uuid.UUID, user: Principal = Depends(require_participant)
):
    """STA-04: recruitment information only; never transfer a booking or its payment.

    An earlier ALTERNATIVE_OFFERED is not final while a consented, paid candidate still awaits a
    successful run. Existing live choices on any of this user's applications are omitted
    from alternatives so the list does not suggest submitting a duplicate candidate.
    """
    try:
        with database_engine().connect() as connection:
            application = (
                connection.execute(
                    text("""SELECT a.state, mp.state AS matching_state FROM application a
                LEFT JOIN match_participation mp ON mp.application_id = a.id
                WHERE a.id = :id AND a.user_id = :user"""),
                    {"id": application_id, "user": user.id},
                )
                .mappings()
                .first()
            )
            if application is None:
                raise HTTPException(404, "application_not_found")
            # Rows written before ADR-0011 say NO_MATCH for the same unseated outcome.
            if application["state"] != "SUBMITTED" or application["matching_state"] not in (
                "ALTERNATIVE_OFFERED",
                "NO_MATCH",
            ):
                raise HTTPException(409, "alternatives_not_available")
            now = locked_now(connection)
            eligible = eligible_slot_ids(connection, [application_id], now)[application_id]
            pending = (
                connection.execute(
                    text(f"""SELECT {SLOT_COLUMNS} FROM event_slot s
                JOIN region r ON r.code = s.region_code
                WHERE s.id = ANY(:ids) AND NOT EXISTS (
                    SELECT 1 FROM match_run m
                    WHERE m.event_slot_id = s.id AND m.state = 'SUCCEEDED')
                ORDER BY s.matches_at, s.id"""),
                    {"ids": eligible},
                )
                .mappings()
                .all()
            )
            alternatives = []
            if not pending:
                alternatives = (
                    connection.execute(
                        text(f"""SELECT {SLOT_COLUMNS} FROM event_slot s
                    JOIN region r ON r.code = s.region_code
                    WHERE s.closes_at > :now AND NOT EXISTS (
                        SELECT 1 FROM application_candidate c
                        WHERE c.event_slot_id = s.id AND c.user_id = :user AND c.live)
                    ORDER BY s.starts_at, r.sort_order, s.id"""),
                        {"user": user.id, "now": now},
                    )
                    .mappings()
                    .all()
                )
            return private_response(
                {
                    "pending_candidates": [slot_json(slot, now) for slot in pending],
                    "alternatives": [slot_json(slot, now) for slot in alternatives],
                }
            )
    except SQLAlchemyError:
        raise HTTPException(503, "application_unavailable") from None


@router.post("/api/me/applications")
def submit_application(
    payload: ApplicationInput, user: Principal = Depends(require_csrf_participant)
):
    application_id = uuid.uuid4()
    try:
        with database_engine().begin() as connection:
            # Serialize this participant's submissions so replay and duplicate checks
            # see every committed application; the unique constraints are the backstop.
            connection.execute(
                text("SELECT id FROM app_user WHERE id = :id FOR UPDATE"), {"id": user.id}
            )
            # Judge deadlines after the lock wait, by the database clock.
            now = locked_now(connection)
            prior = connection.execute(
                text("""SELECT id FROM application
                WHERE user_id = :user_id AND request_key = :key"""),
                {"user_id": user.id, "key": payload.request_key},
            ).scalar()
            if prior is not None:
                chosen = set(
                    connection.execute(
                        text("""SELECT event_slot_id FROM application_candidate
                        WHERE application_id = :id"""),
                        {"id": prior},
                    ).scalars()
                )
                if chosen != set(payload.event_slot_ids):
                    raise HTTPException(409, "request_key_reused")
                (application,) = read_applications(
                    connection, "WHERE a.id = :id", {"id": prior}, now
                )
                return private_response({"application": application})
            if not profile_state(read_profile(connection, user.id))["complete"]:
                raise HTTPException(409, "profile_incomplete")
            if not consent_state(connection, user.id)["complete"]:
                raise HTTPException(409, "consent_incomplete")
            # FOR SHARE lets a later close/match step that locks the slot order itself after us.
            open_slots = connection.execute(
                text("""SELECT id, closes_at FROM event_slot
                WHERE id = ANY(:ids) FOR SHARE"""),
                {"ids": payload.event_slot_ids, "now": now},
            ).all()
            now = locked_now(connection)
            if len(open_slots) != len(payload.event_slot_ids) or any(
                slot.closes_at <= now for slot in open_slots
            ):
                raise field_error("event_slot_ids", "slot_not_recruiting")
            if connection.execute(
                text("""SELECT 1 FROM application_candidate
                WHERE user_id = :user_id AND live AND event_slot_id = ANY(:ids) LIMIT 1"""),
                {"user_id": user.id, "ids": payload.event_slot_ids},
            ).scalar():
                raise HTTPException(409, "application_slot_duplicate")
            consents = latest_consent_ids(connection, user.id)
            connection.execute(
                text("""INSERT INTO application
                (id, user_id, request_key, state, privacy_consent_id, operation_consent_id,
                 submitted_at)
                VALUES (:id, :user_id, :key, 'SUBMITTED', :privacy, :operation, :now)"""),
                {
                    "id": application_id,
                    "user_id": user.id,
                    "key": payload.request_key,
                    "privacy": consents.get("privacy"),
                    "operation": consents.get("operation"),
                    "now": now,
                },
            )
            for slot_id in payload.event_slot_ids:
                connection.execute(
                    text("""INSERT INTO application_candidate
                    (application_id, user_id, event_slot_id) VALUES (:id, :user_id, :slot)"""),
                    {"id": application_id, "user_id": user.id, "slot": slot_id},
                )
            (application,) = read_applications(
                connection, "WHERE a.id = :id", {"id": application_id}, now
            )
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", "")
        if constraint == "application_candidate_live_user_slot":
            raise HTTPException(409, "application_slot_duplicate") from None
        if constraint == "application_user_request":
            raise HTTPException(409, "request_key_reused") from None
        raise HTTPException(503, "application_unavailable") from None
    except SQLAlchemyError:
        raise HTTPException(503, "application_unavailable") from None
    response = private_response({"application": application})
    response.status_code = 201
    return response


@router.post("/api/me/applications/{application_id}/cancel")
def cancel_application(
    application_id: uuid.UUID, user: Principal = Depends(require_csrf_participant)
):
    try:
        with database_engine().begin() as connection:
            # Another participant's id is indistinguishable from a missing one.
            state = connection.execute(
                text("""SELECT state FROM application
                WHERE id = :id AND user_id = :user_id FOR NO KEY UPDATE"""),
                {"id": application_id, "user_id": user.id},
            ).scalar()
            if state is None:
                raise HTTPException(404, "application_not_found")
            now = locked_now(connection)
            if state == "SUBMITTED":
                earliest_close = min(
                    connection.execute(
                        text("""SELECT s.closes_at FROM application_candidate c
                        JOIN event_slot s ON s.id = c.event_slot_id
                        WHERE c.application_id = :id FOR SHARE OF s"""),
                        {"id": application_id},
                    ).scalars()
                )
                # Matching may have held this slot until after the deadline.
                now = locked_now(connection)
                if earliest_close <= now:
                    raise HTTPException(409, "application_cancel_closed")
                connection.execute(
                    text("""UPDATE application SET state = 'CANCELED', canceled_at = :now
                    WHERE id = :id"""),
                    {"id": application_id, "now": now},
                )
                connection.execute(
                    text(
                        "UPDATE application_candidate SET live = false WHERE application_id = :id"
                    ),
                    {"id": application_id},
                )
            (application,) = read_applications(
                connection, "WHERE a.id = :id", {"id": application_id}, now
            )
    except SQLAlchemyError:
        raise HTTPException(503, "application_unavailable") from None
    return private_response({"application": application})


@router.get("/api/admin/applications")
def list_all_applications(operator: Principal = Depends(require_operator)):
    try:
        with database_engine().connect() as connection:
            applications = read_applications(
                connection, "", {}, locked_now(connection), with_participant=True
            )
    except SQLAlchemyError:
        raise HTTPException(503, "application_unavailable") from None
    return private_response({"applications": applications})


@router.get("/api/me/applications")
def list_own_applications(user: Principal = Depends(require_participant)):
    try:
        with database_engine().connect() as connection:
            applications = read_applications(
                connection,
                "WHERE a.user_id = :user_id",
                {"user_id": user.id},
                locked_now(connection),
            )
    except SQLAlchemyError:
        raise HTTPException(503, "application_unavailable") from None
    return private_response({"applications": applications})
