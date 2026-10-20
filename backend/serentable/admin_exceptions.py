"""Work #9 ticket B: one operator list of exceptions and their recorded resolutions.

Resolving only records what the operator decided (state, note, resolver, audit) in one
transaction. It never re-runs or approves a normal flow (operator-console-contract.md).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from serentable.audit import record_audit
from serentable.auth import Principal, private_response, require_csrf_operator, require_operator
from serentable.clock import iso
from serentable.database import database_engine
from serentable.matching_exceptions import MATCHING_FAILURE_SELECT
from serentable.mock_refunds import list_refund_exceptions

router = APIRouter()

# Venue exceptions name a table; push exceptions reach it through their notification.
GATHERING_SELECT = """SELECT g.id, g.kind AS category, g.reason_code, g.state, g.created_at,
    g.updated_at, g.dining_table_id, COALESCE(t.event_slot_id,nt.event_slot_id) AS event_slot_id,
    g.resolution_note, g.resolved_by
    FROM gathering_exception g LEFT JOIN dining_table t ON t.id=g.dining_table_id
    LEFT JOIN push_delivery d ON g.event_key='push:'||d.id::text
    LEFT JOIN app_notification n ON n.id=d.notification_id
    LEFT JOIN dining_table nt ON nt.id::text=split_part(n.event_key,':',2)
      AND (n.event_key LIKE 'table:%' OR n.event_key LIKE 'feedback-reminder:%') """


def gathering_json(row):
    return {
        "kind": "gathering",
        "id": str(row["id"]),
        "category": row["category"],
        "event_slot_id": str(row["event_slot_id"]) if row["event_slot_id"] else None,
        "dining_table_id": str(row["dining_table_id"]) if row["dining_table_id"] else None,
        "reason_code": row["reason_code"],
        "occurred_at": iso(row["created_at"]),
        "state": row["state"],
        "resolution_note": row["resolution_note"],
        "resolved_by": str(row["resolved_by"]) if row["resolved_by"] else None,
        "resolvable": row["state"] == "OPEN" and row["category"] != "VENUE_CONDITIONS",
    }


# An offered alternative left unanswered after its failed slot has started. There is no
# resolution store for it, so it is listed read-only and stays open until the participant
# chooses. ADR-0015 approves this display threshold without expiring participant rights.
ALTERNATIVE_SELECT = """SELECT a.id, mp.reason_code, mp.updated_at, r.event_slot_id
    FROM match_participation mp JOIN application a ON a.id=mp.application_id
    JOIN match_run r ON r.id=mp.match_run_id JOIN event_slot s ON s.id=r.event_slot_id
    WHERE mp.state='ALTERNATIVE_OFFERED' AND a.state='SUBMITTED'
    AND s.starts_at<=clock_timestamp()"""


def alternative_json(row):
    return {
        "kind": "alternative_overdue",
        "id": str(row["id"]),
        "category": "MATCHING_ALTERNATIVE",
        "event_slot_id": str(row["event_slot_id"]),
        "dining_table_id": None,
        "reason_code": row["reason_code"],
        "occurred_at": iso(row["updated_at"]),
        "state": "OPEN",
        "resolution_note": None,
        "resolved_by": None,
        "resolvable": False,
    }


def matching_failure_json(row):
    return {
        "kind": "matching_failure",
        "id": str(row["id"]),
        "category": "MATCHING_FAILURE",
        "event_slot_id": str(row["event_slot_id"]),
        "dining_table_id": None,
        "reason_code": row["reason_code"],
        "occurred_at": iso(row["finished_at"]),
        "state": "OPEN",
        "resolution_note": None,
        "resolved_by": None,
        "resolvable": False,
    }


@router.get("/api/admin/exceptions")
def list_exceptions(
    user: Annotated[Principal, Depends(require_operator)],
    state: Literal["OPEN", "RESOLVED"] | None = None,
):
    with database_engine().connect() as connection:
        items = [
            gathering_json(row)
            for row in connection.execute(
                text(
                    GATHERING_SELECT
                    + """WHERE CAST(:state AS text) IS NULL OR g.state=:state
                    ORDER BY g.created_at DESC, g.id LIMIT 200"""
                ),
                {"state": state},
            ).mappings()
        ]
        items += list_refund_exceptions(connection, state)
        if state != "RESOLVED":
            items += [
                matching_failure_json(row)
                for row in connection.execute(text(MATCHING_FAILURE_SELECT)).mappings()
            ]
            items += [
                alternative_json(row)
                for row in connection.execute(
                    text(ALTERNATIVE_SELECT + " ORDER BY mp.updated_at DESC, a.id LIMIT 200")
                ).mappings()
            ]
    items.sort(key=lambda item: item["occurred_at"], reverse=True)
    return private_response({"exceptions": items})


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=500)


@router.post("/api/admin/exceptions/{kind}/{exception_id}/resolve")
def resolve_exception(
    kind: str,
    exception_id: uuid.UUID,
    payload: ResolveInput,
    operator: Annotated[Principal, Depends(require_csrf_operator)],
):
    """Record the outcome once; an identical repeat returns the same result."""
    if kind in {"alternative_overdue", "matching_failure"}:
        # Listed for visibility only; the participant's own choice is never made for them.
        raise HTTPException(409, "exception_resolution_unsupported")
    if kind != "gathering":
        raise HTTPException(404, "exception_not_found")
    try:
        with database_engine().begin() as connection:
            row = (
                connection.execute(
                    text(GATHERING_SELECT + "WHERE g.id=:id FOR UPDATE OF g"), {"id": exception_id}
                )
                .mappings()
                .first()
            )
            if row is None:
                raise HTTPException(404, "exception_not_found")
            if row["category"] == "VENUE_CONDITIONS":
                raise HTTPException(409, "exception_resolution_unsupported")
            if row["state"] == "OPEN":
                connection.execute(
                    text("""UPDATE gathering_exception SET state='RESOLVED', resolution_note=:note,
                    resolved_by=:operator, updated_at=clock_timestamp() WHERE id=:id"""),
                    {"id": exception_id, "note": payload.note, "operator": operator.id},
                )
                record_audit(
                    connection,
                    operator.id,
                    "exception_resolve",
                    "gathering_exception",
                    exception_id,
                    reason=payload.note,
                    before={"state": "OPEN"},
                    after={"state": "RESOLVED"},
                )
                row = (
                    connection.execute(
                        text(GATHERING_SELECT + "WHERE g.id=:id"), {"id": exception_id}
                    )
                    .mappings()
                    .one()
                )
            elif row["resolution_note"] != payload.note or str(row["resolved_by"]) != operator.id:
                raise HTTPException(409, "exception_already_resolved")
            result = gathering_json(row)
    except SQLAlchemyError:
        # Change and audit roll back together; the exception stays as it was.
        raise HTTPException(503, "exception_resolution_unavailable") from None
    return private_response({"exception": result})
