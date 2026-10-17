"""Explicit participant choices after all paid candidates failed (ADR-0012)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from serentable.auth import Principal, private_response, require_csrf_participant
from serentable.clock import iso, locked_now
from serentable.database import database_engine
from serentable.eligibility import eligible_slot_ids

router = APIRouter()
POLICY_VERSION = "failure-resolution-2026-10-17"
# Shared by workers and participant choices; acquire before any row lock.
MATCHING_LOCK = 7310261017


def lock_matching(connection):
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MATCHING_LOCK})


class ResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    failure_run_id: uuid.UUID
    action: Literal["TRANSFER", "HOLD", "REFUND"]
    event_slot_id: uuid.UUID | None = None


def pending_candidates(connection, application_id, now):
    application_id = uuid.UUID(str(application_id))
    ids = eligible_slot_ids(connection, [application_id], now)[application_id]
    return list(
        connection.execute(
            text("""SELECT s.id FROM event_slot s
        WHERE s.id = ANY(:ids) AND NOT EXISTS (SELECT 1 FROM match_run m
          WHERE m.event_slot_id = s.id AND m.state = 'SUCCEEDED')"""),
            {"ids": ids},
        ).scalars()
    )


def failed_application(connection, application_id, user_id):
    row = (
        connection.execute(
            text("""SELECT a.id, a.user_id, a.state,
        mp.state AS matching_state, mp.reason_code, mp.match_run_id
        FROM application a LEFT JOIN match_participation mp ON mp.application_id=a.id
        WHERE a.id=:id AND a.user_id=:user FOR NO KEY UPDATE OF a"""),
            {"id": application_id, "user": user_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, "application_not_found")
    if (
        row["state"] != "SUBMITTED"
        or row["matching_state"] not in ("ALTERNATIVE_OFFERED", "NO_MATCH")
        or row["reason_code"]
        in ("overlapping_confirmation", "pass_held", "mock_refunded", "membership_held")
        or row["match_run_id"] is None
    ):
        raise HTTPException(409, "resolution_not_available")
    if connection.execute(
        text("""SELECT 1 FROM table_assignment
        WHERE application_id=:id AND ended_at IS NULL"""),
        {"id": application_id},
    ).scalar():
        raise HTTPException(409, "resolution_not_available")
    if not connection.execute(
        text("""SELECT 1 FROM match_run_member rm
        JOIN match_run m ON m.id=rm.match_run_id
        WHERE rm.application_id=:app AND m.id=:run
        AND m.state='SUCCEEDED' AND rm.outcome='UNSEATED'"""),
        {"app": application_id, "run": row["match_run_id"]},
    ).scalar():
        raise HTTPException(409, "resolution_not_available")
    return row


def single_right(connection, application_id):
    return (
        connection.execute(
            text("""SELECT e.id, e.user_id, e.payment_id, p.amount_krw
        FROM entitlement_binding b JOIN entitlement e ON e.id=b.entitlement_id
        JOIN payment p ON p.id=e.payment_id
        WHERE b.application_id=:id AND b.ended_at IS NULL AND e.kind='SINGLE'
          AND p.state='PAID' AND NOT EXISTS (
            SELECT 1 FROM table_assignment ta JOIN entitlement_binding used
            ON used.application_id=ta.application_id WHERE used.entitlement_id=e.id)
        FOR UPDATE OF b, e"""),
            {"id": application_id},
        )
        .mappings()
        .first()
    )


def membership_for_failure(connection, application_id):
    # The failed run is evidence of coverage at the slot; do not pick an unrelated pass
    # merely because it is active today. Extend the latest covering membership once.
    return (
        connection.execute(
            text("""SELECT e.id, e.expires_at FROM entitlement e
        JOIN payment p ON p.id=e.payment_id JOIN application a ON a.user_id=e.user_id
        JOIN match_participation mp ON mp.application_id=a.id
        JOIN match_run m ON m.id=mp.match_run_id JOIN event_slot s ON s.id=m.event_slot_id
        WHERE a.id=:id AND e.kind='MEMBERSHIP' AND p.state='PAID'
          AND e.starts_at <= s.closes_at AND e.expires_at > s.starts_at
        ORDER BY e.expires_at DESC, e.id LIMIT 1 FOR UPDATE OF e"""),
            {"id": application_id},
        )
        .mappings()
        .first()
    )


def extend_final_failure(connection, application_id, now):
    if pending_candidates(connection, application_id, now) or single_right(
        connection, application_id
    ):
        return
    membership = membership_for_failure(connection, application_id)
    if membership is None:
        return
    inserted = connection.execute(
        text("""INSERT INTO membership_extension
        (application_id, entitlement_id, previous_expires_at, expires_at, created_at,
        policy_version)
        VALUES (:app, :ent, :before, :before + interval '7 days', :now, :policy)
        ON CONFLICT (application_id) DO NOTHING RETURNING entitlement_id"""),
        {
            "app": application_id,
            "ent": membership["id"],
            "before": membership["expires_at"],
            "now": now,
            "policy": POLICY_VERSION,
        },
    ).scalar()
    if inserted:
        connection.execute(
            text("UPDATE entitlement SET expires_at=expires_at+interval '7 days' WHERE id=:id"),
            {"id": inserted},
        )


def target_allowed(connection, user_id, slot_id, now):
    return bool(
        connection.execute(
            text("""SELECT 1 FROM event_slot s WHERE s.id=:slot
        AND s.closes_at>:now
        AND NOT EXISTS (SELECT 1 FROM match_run m WHERE m.event_slot_id=s.id AND
        m.state='SUCCEEDED')
        AND NOT EXISTS (SELECT 1 FROM application_candidate c
            WHERE c.user_id=:user AND c.event_slot_id=s.id AND c.live)
        AND NOT EXISTS (SELECT 1 FROM table_assignment ta JOIN event_slot os ON
        os.id=ta.event_slot_id
            WHERE ta.user_id=:user AND ta.ended_at IS NULL
            AND os.starts_at<s.ends_at AND s.starts_at<os.ends_at)"""),
            {"slot": slot_id, "now": now, "user": user_id},
        ).scalar()
    )


def resolution_json(row):
    return {
        "id": str(row["id"]),
        "application_id": str(row["application_id"]),
        "failure_run_id": str(row["failure_run_id"]),
        "action": row["action"],
        "event_slot_id": str(row["event_slot_id"]) if row["event_slot_id"] else None,
        "state": "TRANSFERRED" if row["action"] == "TRANSFER" else row["action"],
        "mock": True,
        "created_at": iso(row["created_at"]),
        "policy_version": row["policy_version"],
    }


@router.post("/api/me/applications/{application_id}/resolutions")
def resolve(
    application_id: uuid.UUID,
    payload: ResolutionInput,
    user: Principal = Depends(require_csrf_participant),
):
    try:
        with database_engine().begin() as connection:
            lock_matching(connection)
            connection.execute(
                text("SELECT id FROM app_user WHERE id=:id FOR UPDATE"), {"id": user.id}
            )
            prior = (
                connection.execute(
                    text("SELECT * FROM match_resolution WHERE user_id=:user AND request_key=:key"),
                    {"user": user.id, "key": payload.request_key},
                )
                .mappings()
                .first()
            )
            if prior:
                if (
                    prior["application_id"],
                    prior["failure_run_id"],
                    prior["action"],
                    prior["event_slot_id"],
                ) != (
                    application_id,
                    payload.failure_run_id,
                    payload.action,
                    payload.event_slot_id,
                ):
                    raise HTTPException(409, "request_key_reused")
                return private_response({"resolution": resolution_json(prior)})
            application = failed_application(connection, application_id, user.id)
            now = locked_now(connection)
            if application["match_run_id"] != payload.failure_run_id or pending_candidates(
                connection, application_id, now
            ):
                raise HTTPException(409, "resolution_not_available")
            if connection.execute(
                text(
                    "SELECT 1 FROM match_resolution "
                    "WHERE application_id=:id AND failure_run_id=:run"
                ),
                {"id": application_id, "run": payload.failure_run_id},
            ).scalar():
                raise HTTPException(409, "resolution_already_chosen")
            if (payload.action == "TRANSFER") != (payload.event_slot_id is not None):
                raise HTTPException(422, "resolution_target_invalid")
            single = single_right(connection, application_id)
            membership = (
                membership_for_failure(connection, application_id) if single is None else None
            )
            if single is None and membership is None:
                raise HTTPException(409, "entitlement_unavailable")
            if payload.action == "REFUND" and single is None:
                raise HTTPException(409, "membership_refund_deferred")
            if payload.action == "TRANSFER":
                connection.execute(
                    text("SELECT id FROM event_slot WHERE id=:id FOR SHARE"),
                    {"id": payload.event_slot_id},
                )
                now = locked_now(connection)
                if not target_allowed(connection, user.id, payload.event_slot_id, now):
                    raise HTTPException(409, "alternative_not_eligible")
                if (
                    single is None
                    and not connection.execute(
                        text("""SELECT 1 FROM entitlement e
                    JOIN payment p ON p.id=e.payment_id JOIN event_slot s ON s.id=:slot
                    WHERE e.user_id=:user AND e.kind='MEMBERSHIP' AND p.state='PAID'
                    AND e.starts_at<=least(:now,s.closes_at) AND e.expires_at>s.starts_at"""),
                        {"slot": payload.event_slot_id, "user": user.id, "now": now},
                    ).scalar()
                ):
                    raise HTTPException(409, "alternative_not_covered")
            extend_final_failure(connection, application_id, now)
            resolution_id = uuid.uuid4()
            row = (
                connection.execute(
                    text("""INSERT INTO match_resolution
                (id, application_id, user_id, failure_run_id, request_key, action, event_slot_id,
                 previous_state, reason_code, created_at, policy_version)
                VALUES (:id,:app,:user,:run,:key,:action,:slot,:previous,:reason,:now,:policy)
                RETURNING *"""),
                    {
                        "id": resolution_id,
                        "app": application_id,
                        "user": user.id,
                        "run": payload.failure_run_id,
                        "key": payload.request_key,
                        "action": payload.action,
                        "slot": payload.event_slot_id,
                        "previous": application["matching_state"],
                        "reason": application["reason_code"],
                        "now": now,
                        "policy": POLICY_VERSION,
                    },
                )
                .mappings()
                .one()
            )
            connection.execute(
                text("UPDATE application_candidate SET live=false WHERE application_id=:id"),
                {"id": application_id},
            )
            if payload.action == "TRANSFER":
                connection.execute(
                    text("""INSERT INTO application_candidate
                    (application_id,user_id,event_slot_id,source_resolution_id)
                    VALUES (:app,:user,:slot,:resolution)"""),
                    {
                        "app": application_id,
                        "user": user.id,
                        "slot": payload.event_slot_id,
                        "resolution": resolution_id,
                    },
                )
                connection.execute(
                    text("""UPDATE match_participation SET state='WAITING',
                    event_slot_id=:slot, match_run_id=NULL, reason_code=NULL, updated_at=:now
                    WHERE application_id=:app"""),
                    {"app": application_id, "slot": payload.event_slot_id, "now": now},
                )
            else:
                if single:
                    connection.execute(
                        text("""UPDATE entitlement_binding SET ended_at=:now
                        WHERE entitlement_id=:id AND ended_at IS NULL"""),
                        {"id": single["id"], "now": now},
                    )
                reason = "pass_held" if single else "membership_held"
                if payload.action == "REFUND":
                    reason = "mock_refunded"
                    for state in ("REFUND_REQUESTED", "REFUND_PROCESSING", "REFUNDED"):
                        connection.execute(
                            text("""INSERT INTO mock_refund_event
                            (resolution_id,payment_id,state,amount_krw,created_at)
                            VALUES (:res,:payment,:state,:amount,:now)"""),
                            {
                                "res": resolution_id,
                                "payment": single["payment_id"],
                                "state": state,
                                "amount": single["amount_krw"],
                                "now": now,
                            },
                        )
                    connection.execute(
                        text("UPDATE payment SET state='REFUNDED' WHERE id=:id AND state='PAID'"),
                        {"id": single["payment_id"]},
                    )
                connection.execute(
                    text("""UPDATE match_participation SET state='NO_MATCH',
                    reason_code=:reason, updated_at=:now WHERE application_id=:app"""),
                    {"app": application_id, "reason": reason, "now": now},
                )
            return private_response({"resolution": resolution_json(row)})
    except IntegrityError:
        raise HTTPException(409, "resolution_conflict") from None
    except SQLAlchemyError:
        raise HTTPException(503, "resolution_unavailable") from None


class ReuseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    application_id: uuid.UUID


def binding_json(row):
    return {
        "id": str(row["id"]),
        "entitlement_id": str(row["entitlement_id"]),
        "application_id": str(row["application_id"]),
        "started_at": iso(row["started_at"]),
    }


@router.post("/api/me/entitlements/{entitlement_id}/reuse")
def reuse(
    entitlement_id: uuid.UUID,
    payload: ReuseInput,
    user: Principal = Depends(require_csrf_participant),
):
    from serentable.payments import payment_details

    try:
        with database_engine().begin() as connection:
            lock_matching(connection)
            connection.execute(
                text("SELECT id FROM app_user WHERE id=:id FOR UPDATE"), {"id": user.id}
            )
            prior = (
                connection.execute(
                    text(
                        "SELECT * FROM entitlement_binding WHERE user_id=:user AND request_key=:key"
                    ),
                    {"user": user.id, "key": payload.request_key},
                )
                .mappings()
                .first()
            )
            if prior:
                if (
                    prior["entitlement_id"] != entitlement_id
                    or prior["application_id"] != payload.application_id
                ):
                    raise HTTPException(409, "request_key_reused")
                return private_response({"binding": binding_json(prior)})
            entitlement = connection.execute(
                text("""SELECT e.id FROM entitlement e
                JOIN payment p ON p.id=e.payment_id WHERE e.id=:id AND e.user_id=:user
                AND e.kind='SINGLE' AND p.state='PAID' FOR UPDATE OF e"""),
                {"id": entitlement_id, "user": user.id},
            ).scalar()
            if entitlement is None:
                raise HTTPException(404, "entitlement_not_found")
            available = connection.execute(
                text("""SELECT 1 WHERE
                NOT EXISTS(SELECT 1 FROM entitlement_binding WHERE entitlement_id=:id AND
                ended_at IS NULL)
                AND NOT EXISTS(SELECT 1 FROM table_assignment ta JOIN entitlement_binding b
                    ON b.application_id=ta.application_id WHERE b.entitlement_id=:id)
                AND EXISTS(SELECT 1 FROM match_resolution r JOIN entitlement_binding b
                    ON b.application_id=r.application_id WHERE b.entitlement_id=:id AND
                    r.action='HOLD')"""),
                {"id": entitlement_id},
            ).scalar()
            if not available:
                raise HTTPException(409, "entitlement_not_reusable")
            application = (
                connection.execute(
                    text("""SELECT id,user_id,state FROM application
                WHERE id=:id AND user_id=:user FOR NO KEY UPDATE"""),
                    {"id": payload.application_id, "user": user.id},
                )
                .mappings()
                .first()
            )
            if application is None:
                raise HTTPException(404, "application_not_found")
            if application["state"] != "SUBMITTED":
                raise HTTPException(409, "application_not_payable")
            slots = (
                connection.execute(
                    text("""SELECT s.closes_at FROM application_candidate c
                JOIN event_slot s ON s.id=c.event_slot_id WHERE c.application_id=:id AND c.live
                FOR SHARE OF s"""),
                    {"id": payload.application_id},
                )
                .scalars()
                .all()
            )
            now = locked_now(connection)
            if not slots or min(slots) <= now:
                raise HTTPException(409, "payment_closed")
            if payment_details(connection, [application], now)[application["id"]]["coverage"]:
                raise HTTPException(409, "entitlement_already_covers")
            row = (
                connection.execute(
                    text("""INSERT INTO entitlement_binding
                (id,entitlement_id,application_id,user_id,request_key,started_at)
                VALUES(:id,:ent,:app,:user,:key,:now) RETURNING *"""),
                    {
                        "id": uuid.uuid4(),
                        "ent": entitlement_id,
                        "app": payload.application_id,
                        "user": user.id,
                        "key": payload.request_key,
                        "now": now,
                    },
                )
                .mappings()
                .one()
            )
            return private_response({"binding": binding_json(row)})
    except IntegrityError:
        raise HTTPException(409, "entitlement_conflict") from None
    except SQLAlchemyError:
        raise HTTPException(503, "resolution_unavailable") from None
