"""Operator audit trail (PRD §16): record inside the caller's transaction, never log PII."""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from serentable.auth import Principal, private_response, require_operator
from serentable.clock import iso
from serentable.database import database_engine

router = APIRouter()


def record_audit(
    connection, actor_id, action, target_type, target_id, *, reason=None, before=None, after=None
):
    """Append one audit row; it commits or rolls back with the change it describes."""
    connection.execute(
        text("""INSERT INTO operator_audit(actor_id, action, target_type, target_id, reason,
        before_state, after_state) VALUES(:actor, :action, :type, :target, :reason,
        CAST(:before AS jsonb), CAST(:after AS jsonb))"""),
        {
            "actor": str(actor_id) if actor_id else None,
            "action": action,
            "type": target_type,
            "target": str(target_id),
            "reason": reason,
            "before": None if before is None else json.dumps(before, default=str),
            "after": None if after is None else json.dumps(after, default=str),
        },
    )


def audit_json(row):
    # The actor is shown by login id only; no display name or contact data (ADR-0008).
    return {
        "id": row["id"],
        "actor": {"login_id": row["login_id"]} if row["login_id"] else None,
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "reason": row["reason"],
        "before": row["before_state"],
        "after": row["after_state"],
        "created_at": iso(row["created_at"]),
    }


@router.get("/api/admin/audit")
def list_audit(
    target_type: str | None = Query(default=None, max_length=32),
    target_id: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    _: Principal = Depends(require_operator),
):
    """Newest first, optionally narrowed to one target type and/or target id."""
    with database_engine().connect() as connection:
        rows = connection.execute(
            text("""SELECT a.*, u.login_id FROM operator_audit a
            LEFT JOIN app_user u ON u.id=a.actor_id
            WHERE (CAST(:type AS text) IS NULL OR a.target_type=:type)
              AND (CAST(:target AS text) IS NULL OR a.target_id=:target)
            ORDER BY a.created_at DESC, a.id DESC LIMIT :limit"""),
            {"type": target_type, "target": target_id, "limit": limit},
        ).mappings()
        result = [audit_json(row) for row in rows]
    return private_response({"audit": result})
