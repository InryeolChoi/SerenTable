"""Work #8 reports, blocks and sanctions (feedback-contract.md, ADR-0014).

A report separates the pair from future matching in the same transaction that stores it
(U09); the operator's review only decides sanctions. Nothing here tells the reported
participant that a report or block exists.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from serentable.audit import record_audit
from serentable.auth import (
    Principal,
    private_response,
    require_csrf_operator,
    require_csrf_participant,
    require_operator,
    require_participant,
)
from serentable.clock import iso
from serentable.database import database_engine
from serentable.match_resolution import lock_matching

router = APIRouter()

REASON_CODES = Literal[
    "harassment", "offensive_language", "unsafe_behavior", "privacy_violation", "other"
]

# Confirmed, still-assigned members of one table (feedback-contract.md 공통 규칙).
SEATED = """SELECT ta.user_id FROM table_assignment ta
    JOIN match_participation mp ON mp.application_id=ta.application_id
      AND mp.user_id=ta.user_id AND mp.dining_table_id=ta.dining_table_id
      AND mp.state='CONFIRMED'
    WHERE ta.dining_table_id=:table_id AND ta.ended_at IS NULL"""


def record_exclusion(connection, a, b, source):
    """Record a symmetric matching exclusion (H5) inside the caller's transaction."""
    # The caller must also acquire this before taking any participant/choice row lock.
    # Reentrant within the transaction; this protects direct exclusion writers as well.
    lock_matching(connection)
    low, high = sorted((str(a), str(b)))
    connection.execute(
        text("""INSERT INTO participant_exclusion(user_low, user_high, source)
        VALUES(:low, :high, :source) ON CONFLICT DO NOTHING"""),
        {"low": low, "high": high, "source": source},
    )


def require_tablemates(connection, table_id, user_id, other_id):
    """404 unless both are confirmed members of the table; the answer never says which."""
    seated = {
        str(member) for member in connection.execute(text(SEATED), {"table_id": table_id}).scalars()
    }
    if str(user_id) == str(other_id) or not {str(user_id), str(other_id)} <= seated:
        raise HTTPException(404, "tablemate_not_found")


REPORT_SELECT = """SELECT r.id, r.reported_id, r.dining_table_id, r.reason_code, r.detail,
    r.state, r.created_at, p.data->>'display_name' AS reported_name
    FROM safety_report r LEFT JOIN participant_profile p ON p.user_id=r.reported_id """


def own_report_json(row):
    """The reporter's own view: their submission and its processing state only."""
    return {
        "id": str(row["id"]),
        "dining_table_id": str(row["dining_table_id"]),
        "reported": {
            "id": str(row["reported_id"]),
            "display_name": row["reported_name"] or "참가자",
        },
        "reason_code": row["reason_code"],
        "detail": row["detail"],
        "state": row["state"],
        "created_at": iso(row["created_at"]),
    }


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dining_table_id: uuid.UUID
    reported_id: uuid.UUID
    reason_code: REASON_CODES
    detail: str | None = Field(default=None, max_length=1000)


@router.post("/api/me/reports")
def create_report(payload: ReportInput, user: Principal = Depends(require_csrf_participant)):
    with database_engine().begin() as connection:
        # Global matching coordination always precedes participant row locks.
        lock_matching(connection)
        # Serialize this reporter so a replay finds the committed report instead of a twin.
        connection.execute(text("SELECT id FROM app_user WHERE id=:id FOR UPDATE"), {"id": user.id})
        require_tablemates(connection, payload.dining_table_id, user.id, payload.reported_id)
        detail = (payload.detail or "").strip() or None
        params = {
            "reporter": user.id,
            "reported": payload.reported_id,
            "table_id": payload.dining_table_id,
            "reason": payload.reason_code,
            "detail": detail,
        }
        # One report per reporter, person and table: a resend returns the stored report.
        existing = (
            connection.execute(
                text(
                    REPORT_SELECT
                    + """WHERE r.reporter_id=:reporter AND r.reported_id=:reported
                    AND r.dining_table_id=:table_id"""
                ),
                params,
            )
            .mappings()
            .first()
        )
        if existing is None:
            report_id = connection.execute(
                text("""INSERT INTO safety_report(id, reporter_id, reported_id,
                dining_table_id, reason_code, detail, created_at)
                VALUES(:id, :reporter, :reported, :table_id, :reason, :detail,
                clock_timestamp()) RETURNING id"""),
                params | {"id": uuid.uuid4()},
            ).scalar_one()
            record_exclusion(connection, user.id, payload.reported_id, "report")
            row = (
                connection.execute(text(REPORT_SELECT + "WHERE r.id=:id"), {"id": report_id})
                .mappings()
                .one()
            )
        else:
            row = existing
        result = own_report_json(row)
    response = private_response({"report": result})
    response.status_code = 200 if existing else 201
    return response


class BlockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dining_table_id: uuid.UUID
    blocked_id: uuid.UUID


@router.post("/api/me/blocks")
def create_block(payload: BlockInput, user: Principal = Depends(require_csrf_participant)):
    with database_engine().begin() as connection:
        lock_matching(connection)
        require_tablemates(connection, payload.dining_table_id, user.id, payload.blocked_id)
        record_exclusion(connection, user.id, payload.blocked_id, "block")
    # Blocks leave no per-direction record, so nothing can show who blocked whom.
    return private_response({"blocked": True})


@router.get("/api/me/tables/{table_id}/safety")
def table_safety(table_id: uuid.UUID, user: Principal = Depends(require_participant)):
    """Tablemates to report or block, and only the reports this participant filed."""
    with database_engine().connect() as connection:
        mates = (
            connection.execute(
                text(
                    "SELECT s.user_id, p.data->>'display_name' AS display_name FROM ("
                    + SEATED
                    + """) s LEFT JOIN participant_profile p ON p.user_id=s.user_id
                    ORDER BY display_name NULLS LAST, s.user_id"""
                ),
                {"table_id": table_id},
            )
            .mappings()
            .all()
        )
        if str(user.id) not in {str(mate["user_id"]) for mate in mates}:
            raise HTTPException(404, "table_not_found")
        reports = [
            own_report_json(row)
            for row in connection.execute(
                text(
                    REPORT_SELECT
                    + """WHERE r.reporter_id=:user_id AND r.dining_table_id=:table_id
                    ORDER BY r.created_at, r.id"""
                ),
                {"user_id": user.id, "table_id": table_id},
            ).mappings()
        ]
    return private_response(
        {
            "tablemates": [
                {"id": str(mate["user_id"]), "display_name": mate["display_name"] or "참가자"}
                for mate in mates
                if str(mate["user_id"]) != str(user.id)
            ],
            "reports": reports,
        }
    )


ADMIN_REPORT_SELECT = """SELECT r.*, reporter.login_id AS reporter_login,
    reporter_p.data->>'display_name' AS reporter_name,
    reported.login_id AS reported_login, reported_p.data->>'display_name' AS reported_name
    FROM safety_report r
    JOIN app_user reporter ON reporter.id=r.reporter_id
    JOIN app_user reported ON reported.id=r.reported_id
    LEFT JOIN participant_profile reporter_p ON reporter_p.user_id=r.reporter_id
    LEFT JOIN participant_profile reported_p ON reported_p.user_id=r.reported_id """


def person_json(user_id, login_id, display_name):
    return {"id": str(user_id), "login_id": login_id, "display_name": display_name}


def admin_report_json(row):
    return {
        "id": str(row["id"]),
        "dining_table_id": str(row["dining_table_id"]) if row["dining_table_id"] else None,
        "reporter": person_json(row["reporter_id"], row["reporter_login"], row["reporter_name"]),
        "reported": person_json(row["reported_id"], row["reported_login"], row["reported_name"]),
        "reason_code": row["reason_code"],
        "detail": row["detail"],
        "state": row["state"],
        "created_at": iso(row["created_at"]),
        "reviewed_at": iso(row["reviewed_at"]),
    }


def read_admin_report(connection, report_id):
    row = (
        connection.execute(text(ADMIN_REPORT_SELECT + "WHERE r.id=:id"), {"id": report_id})
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, "report_not_found")
    return row


@router.get("/api/admin/reports")
def list_reports(_: Principal = Depends(require_operator)):
    with database_engine().connect() as connection:
        rows = connection.execute(
            text(ADMIN_REPORT_SELECT + "ORDER BY (r.state='OPEN') DESC, r.created_at DESC, r.id")
        ).mappings()
        result = [admin_report_json(row) for row in rows]
    return private_response({"reports": result})


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["CONFIRMED", "DISMISSED"]


@router.post("/api/admin/reports/{report_id}/review")
def review_report(
    report_id: uuid.UUID,
    payload: ReviewInput,
    operator: Principal = Depends(require_csrf_operator),
):
    """Record the decision once. The pair stays separated either way (U09)."""
    with database_engine().begin() as connection:
        connection.execute(
            text("SELECT id FROM safety_report WHERE id=:id FOR UPDATE"), {"id": report_id}
        )
        row = read_admin_report(connection, report_id)
        if row["state"] == "OPEN":
            connection.execute(
                text("""UPDATE safety_report SET state=:decision, reviewed_by=:operator,
                reviewed_at=clock_timestamp() WHERE id=:id"""),
                {"id": report_id, "decision": payload.decision, "operator": operator.id},
            )
            # States only: the report's detail text never enters the audit trail.
            record_audit(
                connection,
                operator.id,
                "report.review",
                "safety_report",
                report_id,
                before={"state": "OPEN"},
                after={"state": payload.decision},
            )
            row = read_admin_report(connection, report_id)
        elif row["state"] != payload.decision:
            raise HTTPException(409, "report_already_reviewed")
        result = admin_report_json(row)
    return private_response({"report": result})


ACTIVE_RESTRICTION = """SELECT 1 FROM participant_sanction WHERE user_id=:user_id
    AND (kind='PERMANENT_BAN' OR (kind='SUSPENSION' AND ends_at > :now)) LIMIT 1"""


def participation_restricted(connection, user_id, now):
    """An active suspension or a permanent ban blocks new applications; warnings do not."""
    return (
        connection.execute(text(ACTIVE_RESTRICTION), {"user_id": user_id, "now": now}).scalar()
        is not None
    )


SANCTION_SELECT = """SELECT s.*, u.login_id, p.data->>'display_name' AS display_name,
    (s.kind='PERMANENT_BAN' OR (s.kind='SUSPENSION' AND s.ends_at > clock_timestamp()))
        AS restricting
    FROM participant_sanction s JOIN app_user u ON u.id=s.user_id
    LEFT JOIN participant_profile p ON p.user_id=s.user_id """


def sanction_json(row):
    return {
        "id": str(row["id"]),
        "user": person_json(row["user_id"], row["login_id"], row["display_name"]),
        "kind": row["kind"],
        "report_id": str(row["report_id"]) if row["report_id"] else None,
        "ends_at": iso(row["ends_at"]),
        "created_at": iso(row["created_at"]),
        "restricting": row["restricting"],
    }


class SanctionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    kind: Literal["WARNING", "SUSPENSION", "PERMANENT_BAN"]
    report_id: uuid.UUID | None = None
    ends_at: datetime | None = None


@router.post("/api/admin/sanctions")
def create_sanction(payload: SanctionInput, operator: Principal = Depends(require_csrf_operator)):
    if (payload.kind == "SUSPENSION") != (payload.ends_at is not None):
        raise HTTPException(422, "ends_at_only_for_suspension")
    if payload.ends_at is not None and payload.ends_at.tzinfo is None:
        raise HTTPException(422, "ends_at_timezone_required")
    with database_engine().begin() as connection:
        target = connection.execute(
            text("SELECT role FROM app_user WHERE id=:id FOR UPDATE"), {"id": payload.user_id}
        ).scalar()
        if target != "participant":
            raise HTTPException(404, "participant_not_found")
        now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        if payload.ends_at is not None and payload.ends_at <= now:
            raise HTTPException(422, "ends_at_not_future")
        if payload.report_id is not None:
            linked = (
                connection.execute(
                    text("SELECT reported_id, state FROM safety_report WHERE id=:id"),
                    {"id": payload.report_id},
                )
                .mappings()
                .first()
            )
            if linked is None or str(linked["reported_id"]) != str(payload.user_id):
                raise HTTPException(404, "report_not_found")
            if linked["state"] != "CONFIRMED":
                raise HTTPException(409, "report_not_confirmed")
        params = {
            "user_id": payload.user_id,
            "kind": payload.kind,
            "report_id": payload.report_id,
            "ends_at": payload.ends_at,
        }
        # The same sanction sent twice is stored once (the target row lock serializes it).
        existing = connection.execute(
            text("""SELECT id FROM participant_sanction WHERE user_id=:user_id AND kind=:kind
            AND report_id IS NOT DISTINCT FROM :report_id
            AND ends_at IS NOT DISTINCT FROM :ends_at"""),
            params,
        ).scalar()
        sanction_id = (
            existing
            or connection.execute(
                text("""INSERT INTO participant_sanction(id, user_id, kind, report_id, ends_at,
            created_by, created_at)
            VALUES(:id, :user_id, :kind, :report_id, :ends_at, :operator, :now) RETURNING id"""),
                params | {"id": uuid.uuid4(), "operator": operator.id, "now": now},
            ).scalar_one()
        )
        if not existing:
            record_audit(
                connection,
                operator.id,
                "sanction.create",
                "participant",
                payload.user_id,
                after={
                    "sanction_id": str(sanction_id),
                    "kind": payload.kind,
                    "report_id": str(payload.report_id) if payload.report_id else None,
                    "ends_at": iso(payload.ends_at),
                },
            )
        row = (
            connection.execute(text(SANCTION_SELECT + "WHERE s.id=:id"), {"id": sanction_id})
            .mappings()
            .one()
        )
        result = sanction_json(row)
    response = private_response({"sanction": result})
    response.status_code = 200 if existing else 201
    return response


@router.get("/api/admin/sanctions")
def list_sanctions(_: Principal = Depends(require_operator)):
    with database_engine().connect() as connection:
        rows = connection.execute(
            text(SANCTION_SELECT + "ORDER BY s.created_at DESC, s.id")
        ).mappings()
        result = [sanction_json(row) for row in rows]
    return private_response({"sanctions": result})
