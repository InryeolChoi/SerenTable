"""Mock-only refund persistence: bounded savepoint failures and operator retry."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from serentable.audit import record_audit
from serentable.auth import Principal, private_response, require_csrf_operator, require_operator
from serentable.clock import iso, locked_now
from serentable.database import database_engine

router = APIRouter()


def attempt_json(row):
    return {
        "id": row["id"],
        "attempt_number": row["attempt_number"],
        "state": row["state"],
        "error_code": row["error_code"],
        "created_at": iso(row["created_at"]),
    }


def refund_status(connection, resolution_id):
    state = connection.execute(
        text("""SELECT state FROM mock_refund_attempt
        WHERE resolution_id=:id ORDER BY attempt_number DESC LIMIT 1"""),
        {"id": resolution_id},
    ).scalar()
    if state:
        return state
    # Old successful refund evidence remains valid without manufacturing attempts.
    return (
        "SUCCEEDED"
        if connection.execute(
            text("""SELECT 1 FROM mock_refund_event
        WHERE resolution_id=:id AND state='REFUNDED'"""),
            {"id": resolution_id},
        ).scalar()
        else None
    )


def perform_refund(connection, resolution_id, single, request_key, now, operator_id=None):
    """Only this DB-only financial operation may fail persistently.

    SAVEPOINT leaves the surrounding transaction usable after a statement failure.
    Connection loss, failure-record writes, audit or outer commit failures still abort
    everything and return 503: no DB can promise evidence while unavailable.
    """
    state, error_code = "SUCCEEDED", None
    try:
        with connection.begin_nested():
            changed = connection.execute(
                text("""UPDATE payment SET state='REFUNDED'
                WHERE id=:id AND state='PAID' RETURNING id"""),
                {"id": single["payment_id"]},
            ).scalar()
            if changed is None:
                raise HTTPException(409, "refund_not_available")
            for event in ("REFUND_REQUESTED", "REFUND_PROCESSING", "REFUNDED"):
                connection.execute(
                    text("""INSERT INTO mock_refund_event
                    (resolution_id,payment_id,state,amount_krw,created_at)
                    VALUES (:res,:payment,:state,:amount,:now)"""),
                    {
                        "res": resolution_id,
                        "payment": single["payment_id"],
                        "state": event,
                        "amount": single["amount_krw"],
                        "now": now,
                    },
                )
            connection.execute(
                text("""UPDATE entitlement_binding SET ended_at=:now
                WHERE entitlement_id=:id AND ended_at IS NULL"""),
                {"id": single["id"], "now": now},
            )
    except SQLAlchemyError:
        state, error_code = "FAILED", "mock_refund_storage_failed"
    attempt = (
        connection.execute(
            text("""INSERT INTO mock_refund_attempt
        (resolution_id,request_key,operator_id,payment_id,amount_krw,
         attempt_number,state,error_code,created_at)
        SELECT :res,:key,:operator,:payment,:amount,
            coalesce(max(attempt_number),0)+1,:state,:error,:now
        FROM mock_refund_attempt WHERE resolution_id=:res RETURNING *"""),
            {
                "res": resolution_id,
                "key": request_key,
                "operator": operator_id,
                "payment": single["payment_id"],
                "amount": single["amount_krw"],
                "state": state,
                "error": error_code,
                "now": now,
            },
        )
        .mappings()
        .one()
    )
    return attempt


REFUND_SELECT = """SELECT r.id, r.application_id, r.user_id, r.failure_run_id,
    r.created_at AS requested_at, p.id AS payment_id, a.amount_krw, p.state AS payment_state,
    m.event_slot_id, a.state, a.error_code, a.attempt_number, a.created_at
    FROM match_resolution r JOIN mock_refund_attempt a ON a.resolution_id=r.id
    JOIN match_run m ON m.id=r.failure_run_id
    JOIN payment p ON p.id=a.payment_id
    WHERE r.action='REFUND' AND a.attempt_number=(SELECT max(last.attempt_number)
        FROM mock_refund_attempt last WHERE last.resolution_id=r.id)"""


def refund_json(row):
    return {
        "id": str(row["id"]),
        "application_id": str(row["application_id"]),
        "event_slot_id": str(row["event_slot_id"]),
        "amount_krw": row["amount_krw"],
        "state": row["state"],
        "error_code": row["error_code"],
        "attempt_number": row["attempt_number"],
        "created_at": iso(row["created_at"]),
        "mock": True,
    }


def list_refunds(connection, state="FAILED", *, failed_history_only=False):
    return [
        refund_json(row)
        for row in connection.execute(
            text(
                REFUND_SELECT
                + (
                    " AND EXISTS(SELECT 1 FROM mock_refund_attempt failed "
                    "WHERE failed.resolution_id=r.id AND failed.state='FAILED')"
                    if failed_history_only
                    else ""
                )
                + " AND (CAST(:state AS text) IS NULL OR a.state=:state)"
                + " ORDER BY a.created_at DESC, r.id LIMIT 200"
            ),
            {"state": state},
        ).mappings()
    ]


def list_refund_exceptions(connection, state=None):
    return [
        {
            "kind": "mock_refund",
            "id": row["id"],
            "category": "MOCK_REFUND",
            "event_slot_id": row["event_slot_id"],
            "dining_table_id": None,
            "reason_code": row["error_code"],
            "occurred_at": row["created_at"],
            "state": "OPEN" if row["state"] == "FAILED" else "RESOLVED",
            "resolution_note": None,
            "resolved_by": None,
            "resolvable": False,
            "retryable": row["state"] == "FAILED",
            "amount_krw": row["amount_krw"],
        }
        for row in list_refunds(
            connection,
            "FAILED" if state == "OPEN" else "SUCCEEDED" if state == "RESOLVED" else None,
            failed_history_only=True,
        )
    ]


@router.get("/api/admin/mock-refunds")
def get_refunds(
    state: Literal["FAILED", "SUCCEEDED"] | None = "FAILED",
    _: Principal = Depends(require_operator),
):
    with database_engine().connect() as connection:
        return private_response({"refunds": list_refunds(connection, state)})


class RetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID


@router.post("/api/admin/mock-refunds/{resolution_id}/retry")
def retry_refund(
    resolution_id: uuid.UUID,
    payload: RetryInput,
    operator: Principal = Depends(require_csrf_operator),
):
    from serentable.match_resolution import lock_matching, single_right

    try:
        with database_engine().begin() as connection:
            lock_matching(connection)
            row = (
                connection.execute(
                    text("""SELECT r.* FROM match_resolution r
                WHERE r.id=:id AND r.action='REFUND' FOR UPDATE"""),
                    {"id": resolution_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise HTTPException(404, "refund_not_found")
            prior = (
                connection.execute(
                    text("""SELECT * FROM mock_refund_attempt
                WHERE request_key=:key AND (operator_id=:operator OR resolution_id=:id)"""),
                    {"operator": operator.id, "key": payload.request_key, "id": resolution_id},
                )
                .mappings()
                .first()
            )
            if prior:
                if (
                    prior["resolution_id"] != resolution_id
                    or str(prior["operator_id"]) != operator.id
                ):
                    raise HTTPException(409, "request_key_reused")
                return private_response({"refund": attempt_json(prior)})
            if refund_status(connection, resolution_id) != "FAILED":
                raise HTTPException(409, "refund_not_retryable")
            connection.execute(
                text("SELECT id FROM app_user WHERE id=:id FOR UPDATE"), {"id": row["user_id"]}
            )
            application_state = connection.execute(
                text("""SELECT a.state FROM application a
                JOIN match_participation mp ON mp.application_id=a.id
                WHERE a.id=:id AND mp.state='NO_MATCH' AND mp.reason_code='mock_refund_failed'
                FOR NO KEY UPDATE OF a"""),
                {"id": row["application_id"]},
            ).scalar()
            if application_state != "SUBMITTED":
                raise HTTPException(409, "refund_not_retryable")
            single = single_right(connection, row["application_id"])
            original = (
                connection.execute(
                    text("""SELECT payment_id,amount_krw
                FROM mock_refund_attempt WHERE resolution_id=:id
                ORDER BY attempt_number LIMIT 1"""),
                    {"id": resolution_id},
                )
                .mappings()
                .one()
            )
            if single is not None and (single["payment_id"], single["amount_krw"]) != (
                original["payment_id"],
                original["amount_krw"],
            ):
                raise HTTPException(409, "refund_not_retryable")
            if (
                single is None
                or connection.execute(
                    text("""SELECT 1 FROM table_assignment
                WHERE application_id=:id AND ended_at IS NULL"""),
                    {"id": row["application_id"]},
                ).scalar()
            ):
                raise HTTPException(409, "refund_not_retryable")
            now = locked_now(connection)
            attempt = perform_refund(
                connection, resolution_id, single, payload.request_key, now, operator.id
            )
            connection.execute(
                text("""UPDATE match_participation SET reason_code=:reason,
                updated_at=:now WHERE application_id=:app AND state='NO_MATCH'"""),
                {
                    "app": row["application_id"],
                    "now": now,
                    "reason": "mock_refunded"
                    if attempt["state"] == "SUCCEEDED"
                    else "mock_refund_failed",
                },
            )
            record_audit(
                connection,
                operator.id,
                "mock_refund_retry",
                "match_resolution",
                resolution_id,
                before={"state": "FAILED"},
                after={"state": attempt["state"], "attempt_number": attempt["attempt_number"]},
            )
            return private_response({"refund": attempt_json(attempt)})
    except SQLAlchemyError:
        raise HTTPException(503, "mock_refund_unavailable") from None
