"""Operator audit trail (PRD §16): record inside the caller's transaction, never log PII."""

import json

from fastapi import APIRouter
from sqlalchemy import text

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
