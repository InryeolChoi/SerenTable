"""Time helpers shared by the API modules."""

from datetime import timedelta, timezone

from sqlalchemy import text

# Korea observes no daylight saving time, so a fixed offset is exact for display.
SEOUL = timezone(timedelta(hours=9))


def iso(value):
    return value.isoformat() if value else None


def locked_now(connection):
    """The database clock at this point; unlike now(), it advances within a transaction.

    Read it after taking the locks a deadline decision depends on, so a lock wait that
    outlasts a deadline is judged after the deadline.
    """
    return connection.execute(text("SELECT clock_timestamp()")).scalar()
