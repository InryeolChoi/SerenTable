"""Work #8 shared foundation: schema 0012 and the exclusion recorder (ADR-0014)."""

import pytest
from serentable.database import database_engine
from serentable.safety import record_exclusion
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from support import truncate


def users(connection):
    rows = connection.execute(
        text("SELECT id FROM app_user WHERE role = 'participant' ORDER BY login_id LIMIT 2")
    ).scalars()
    return list(rows)


def test_exclusions_are_symmetric_idempotent_and_accept_immediate_reports(seeded_database):
    truncate("participant_exclusion")
    with database_engine().begin() as connection:
        a, b = users(connection)
        record_exclusion(connection, b, a, "report")
        record_exclusion(connection, a, b, "report")
        record_exclusion(connection, a, b, "avoid")
    with database_engine().connect() as connection:
        rows = connection.execute(
            text("SELECT user_low, user_high, source FROM participant_exclusion ORDER BY source")
        ).all()
    low, high = sorted((str(a), str(b)))
    assert [(str(r[0]), str(r[1]), r[2]) for r in rows] == [
        (low, high, "avoid"),
        (low, high, "report"),
    ]
    truncate("participant_exclusion")


def test_schema_rejects_self_preferences_and_unbounded_ratings(seeded_database):
    with database_engine().connect() as connection:
        a, _ = users(connection)
    with database_engine().connect() as connection:
        with pytest.raises(IntegrityError), connection.begin():
            connection.execute(
                text("""INSERT INTO safety_report(id, reporter_id, reported_id, reason_code,
                created_at) VALUES(gen_random_uuid(), :a, :a, 'other', now())"""),
                {"a": a},
            )
        with pytest.raises(IntegrityError), connection.begin():
            connection.execute(
                text("""INSERT INTO participant_sanction(id, user_id, kind, created_by,
                created_at) VALUES(gen_random_uuid(), :a, 'SUSPENSION', :a, now())"""),
                {"a": a},
            )
