"""Work #9 exports API (operator-console-contract.md D, PRD §16).

Operator-only CSV downloads per slot. Participants are identified by internal id and
display name only: no contact, Instagram, real name or report text ever leaves here
(ADR-0008). Every export is itself recorded in the operator audit trail.
"""

import csv
import io
import uuid
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from serentable.audit import record_audit
from serentable.auth import Principal, require_operator
from serentable.database import database_engine

router = APIRouter()

SEOUL = timezone(timedelta(hours=9))
# Spreadsheet apps evaluate a cell that starts with one of these as a formula.
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
UNNAMED = "참가자"

APPLICATION_HEADER = ["신청 ID", "표시명", "신청 상태", "결제 상태", "매칭 상태", "제출 시각"]
# Latest payment attempt per application; FAILED history never hides a later PAID one.
APPLICATION_ROWS = """SELECT a.id, p.data ->> 'display_name' AS display_name, a.state,
    pay.state AS payment_state, mp.state AS matching_state, a.submitted_at
    FROM application a
    JOIN application_candidate c ON c.application_id = a.id AND c.event_slot_id = :slot
    LEFT JOIN participant_profile p ON p.user_id = a.user_id
    LEFT JOIN match_participation mp ON mp.application_id = a.id
    LEFT JOIN LATERAL (
        SELECT state FROM payment WHERE application_id = a.id
        ORDER BY requested_at DESC, id DESC LIMIT 1
    ) pay ON true
    ORDER BY a.submitted_at NULLS LAST, a.id"""


def guard(value):
    """Neutralise CSV formula injection: prefix a quote to a cell a sheet would evaluate."""
    cell = "" if value is None else str(value)
    return "'" + cell if cell.startswith(FORMULA_TRIGGERS) else cell


def seoul_time(value):
    return value.astimezone(SEOUL).replace(microsecond=0).isoformat() if value else ""


def csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([guard(cell) for cell in row] for row in rows)
    # The BOM lets spreadsheet apps read the Korean text as UTF-8.
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def export_slot(operator, slot_id, kind, header, build):
    """Read the rows and record the export in one transaction."""
    try:
        with database_engine().begin() as connection:
            if not connection.execute(
                text("SELECT 1 FROM event_slot WHERE id = :slot"), {"slot": slot_id}
            ).scalar():
                raise HTTPException(404, "event_slot_not_found")
            rows = build(connection, slot_id)
            record_audit(
                connection,
                operator.id,
                "export",
                "event_slot",
                slot_id,
                after={"file": kind, "rows": len(rows)},
            )
    except SQLAlchemyError:
        raise HTTPException(503, "export_unavailable") from None
    return csv_response(f"{kind}-{slot_id}.csv", header, rows)


def application_rows(connection, slot_id):
    return [
        [
            str(row["id"]),
            row["display_name"] or UNNAMED,
            row["state"],
            row["payment_state"] or "",
            row["matching_state"] or "",
            seoul_time(row["submitted_at"]),
        ]
        for row in connection.execute(text(APPLICATION_ROWS), {"slot": slot_id}).mappings()
    ]


@router.get("/api/admin/exports/applications.csv")
def export_applications(
    event_slot_id: uuid.UUID = Query(), operator: Principal = Depends(require_operator)
):
    return export_slot(
        operator, event_slot_id, "applications", APPLICATION_HEADER, application_rows
    )


TABLE_HEADER = ["테이블 ID", "점수", "인원", "표시명 목록", "식당명", "체크인 수"]
TABLE_ROWS = """SELECT t.id, t.score, v.name AS venue_name,
    (SELECT count(*) FROM attendance_check_in ci WHERE ci.dining_table_id = t.id)
        AS check_ins
    FROM dining_table t
    JOIN match_run r ON r.id = t.match_run_id AND r.state = 'SUCCEEDED'
    LEFT JOIN venue_allocation a ON a.dining_table_id = t.id
    LEFT JOIN venue_inventory v ON v.id = a.inventory_id
    WHERE t.event_slot_id = :slot
    ORDER BY t.created_at, t.id"""
# Live seats only: a reallocated member is listed at the table they now hold.
TABLE_MEMBERS = """SELECT ta.dining_table_id, ta.user_id,
    p.data ->> 'display_name' AS display_name
    FROM table_assignment ta
    JOIN match_participation mp ON mp.application_id = ta.application_id
      AND mp.user_id = ta.user_id AND mp.dining_table_id = ta.dining_table_id
      AND mp.event_slot_id = ta.event_slot_id AND mp.state = 'CONFIRMED'
    LEFT JOIN participant_profile p ON p.user_id = ta.user_id
    WHERE ta.event_slot_id = :slot AND ta.ended_at IS NULL"""


def table_rows(connection, slot_id):
    names = {}
    for row in connection.execute(text(TABLE_MEMBERS), {"slot": slot_id}).mappings():
        names.setdefault(row["dining_table_id"], []).append(
            (row["display_name"] or UNNAMED, str(row["user_id"]))
        )
    return [
        [
            str(row["id"]),
            # Runs before ADR-0011 recorded no score.
            "" if row["score"] is None else f"{row['score']:.2f}",
            len(names.get(row["id"], [])),
            ", ".join(name for name, _ in sorted(names.get(row["id"], []))),
            row["venue_name"] or "",
            row["check_ins"],
        ]
        for row in connection.execute(text(TABLE_ROWS), {"slot": slot_id}).mappings()
    ]


@router.get("/api/admin/exports/tables.csv")
def export_tables(
    event_slot_id: uuid.UUID = Query(), operator: Principal = Depends(require_operator)
):
    return export_slot(operator, event_slot_id, "tables", TABLE_HEADER, table_rows)
