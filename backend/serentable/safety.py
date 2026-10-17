"""Work #8 reports, blocks and sanctions (feedback-contract.md, ADR-0014)."""

from fastapi import APIRouter
from sqlalchemy import text

router = APIRouter()


def record_exclusion(connection, a, b, source):
    """Record a symmetric matching exclusion (H5) inside the caller's transaction."""
    low, high = sorted((str(a), str(b)))
    connection.execute(
        text("""INSERT INTO participant_exclusion(user_low, user_high, source)
        VALUES(:low, :high, :source) ON CONFLICT DO NOTHING"""),
        {"low": low, "high": high, "source": source},
    )
