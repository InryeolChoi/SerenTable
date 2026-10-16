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
    subprocess.run([sys.executable, "-m", "serentable.seed_demo_accounts"], check=True)
