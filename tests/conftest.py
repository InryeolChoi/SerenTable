import os
import subprocess
import sys

import pytest
from support import ORIGIN


@pytest.fixture
def seeded_database(monkeypatch):
    """The real test PostgreSQL at head with the synthetic demo accounts seeded."""
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setenv("AUTH_SIGNING_KEY", "local-integration-test-signing-key-1234567890")
    monkeypatch.setenv("DEMO_PARTICIPANT_PASSWORD", "synthetic-participant-password")
    monkeypatch.setenv("DEMO_OPERATOR_PASSWORD", "synthetic-operator-password")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    # Safety preferences and restrictions are deliberately durable in the product.
    # Independent test scenarios must not inherit another test's exclusions or sanctions.
    from serentable.database import database_engine
    from sqlalchemy import text

    with database_engine().begin() as connection:
        audit = connection.execute(text("SELECT to_regclass('public.operator_audit')")).scalar()
        connection.execute(
            text(
                """TRUNCATE participant_exclusion, participant_sanction,
            person_preference, safety_report, attendance_check_in, no_show_review,
            table_feedback, push_subscription, app_notification"""
                + (", operator_audit" if audit else "")
                + " CASCADE"
            )
        )
    subprocess.run([sys.executable, "-m", "serentable.seed_demo_accounts"], check=True)
