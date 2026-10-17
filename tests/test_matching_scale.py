"""100 synthetic applicants through real PostgreSQL, HTTP and the separate worker.

No data/ files, shared seed rules or performance SLA are involved. Account provisioning
is a test fixture; all profile, consent, application, payment and result behavior uses
HTTP. The independent oracle validates the saved tables read from the operator API.
"""

import os
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from oracle.hard_constraints import Participant, Table, validate_assignment
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login, truncate
from test_applications import apply
from test_matching_runner import due_slot, matching_database, prepare  # noqa: F401
from test_payments import pay


@pytest.fixture
def hundred_accounts():
    accounts = [
        {"id": uuid.uuid4(), "login_id": f"synthetic-scale-{index:03d}"} for index in range(100)
    ]
    with database_engine().begin() as connection:
        connection.execute(
            text("""INSERT INTO app_user (id, login_id, password_hash, role, active)
            SELECT :id, :login_id, password_hash, 'participant', true
            FROM app_user WHERE login_id = 'participant-01'"""),
            accounts,
        )
    try:
        yield accounts
    finally:
        # This is the same disposable local test DB as the ordinary fixture. Remove only
        # the added accounts after clearing the test business rows; no account leaks into
        # later tests that expect the four ordinary demo participants.
        truncate(
            "event_slot, participant_profile, consent_record, app_notification, push_subscription"
        )
        ids = [account["id"] for account in accounts]
        with database_engine().begin() as connection:
            connection.execute(
                text("DELETE FROM auth_session WHERE user_id = ANY(:ids)"), {"ids": ids}
            )
            connection.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": ids})


def test_a_separate_worker_confirms_100_paid_applicants_without_hard_violations(hundred_accounts):
    # 50 + 50 in two incompatible age groups. A witness of ten tables of five per group
    # seats all 100, the trivial upper bound. This known optimum is independent of the
    # planner; no 100-person brute force or copied dynamic program is used as an oracle.
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        for index, account in enumerate(hundred_accounts):
            prepare(participant, account["login_id"], birth_year=1990 if index < 50 else 2005)
        slot = due_slot(operator, close_in=45, capacity=100)
        deadline = time.monotonic() + 45.7
        roster = []
        for index, account in enumerate(hundred_accounts):
            login(participant, account["login_id"])
            response = apply(participant, [slot])
            assert response.status_code == 201, response.text
            application_id = response.json()["application"]["id"]
            assert pay(participant, application_id, "single").status_code == 201
            roster.append(
                Participant(
                    id=application_id,
                    paid=True,
                    consented_slots=frozenset({slot}),
                    birth_year=1990 if index < 50 else 2005,
                )
            )
        time.sleep(max(0, deadline - time.monotonic()))
        started = time.monotonic()
        worker = subprocess.run(
            [sys.executable, "-m", "serentable.worker", "--once"],
            env={**os.environ, "PYTHONPATH": "backend"},
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        duration = time.monotonic() - started
        assert "worker_matching_ok runs=1" in worker.stderr
        history = operator.get("/api/admin/match-runs")
        assert history.status_code == 200
        (run,) = history.json()["match_runs"]
        assert run["state"] == "SUCCEEDED" and run["seated_count"] == 100
        assert len(run["members"]) == 100
        groups = {}
        for member in run["members"]:
            assert member["outcome"] == "SEATED"
            groups.setdefault(member["dining_table_id"], []).append(member["application_id"])
        tables = [
            Table(table_id=key, slot=slot, members=tuple(members))
            for key, members in groups.items()
        ]
        assert validate_assignment(roster, tables) == []
        for account in (hundred_accounts[0], hundred_accounts[-1]):
            login(participant, account["login_id"])
            (application,) = participant.get("/api/me/applications").json()["applications"]
            assert application["matching"]["state"] == "CONFIRMED"
            assert application["coverage"]["entitlement"]["state"] == "USED"
        # Process startup + DB work is measured, not asserted against an unapproved SLA.
        print(f"synthetic_100_worker_seconds={duration:.3f} tables={len(tables)} seated=100")
