"""Work #4 Task ②: failure, duplicate and deadline scenarios over HTTP on real PostgreSQL.

Matching eligibility is read from the operator's application list
(`matching_eligible_slot_ids`), the same predicate the matching worker will use.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from serentable.clock import locked_now
from serentable.database import database_engine
from serentable.eligibility import matching_eligible_applications
from serentable.main import app
from support import login, send
from test_applications import (  # noqa: F401
    application_database,
    apply,
    create_slot,
    hold_lock,
    make_ready,
)
from test_payments import pay


def submitted(operator, participant, login_id, days=7, close_in=timedelta(days=3)):
    login(participant, login_id)
    make_ready(participant)
    slot = create_slot(operator, days=days, close_in=close_in)
    response = apply(participant, [slot])
    assert response.status_code == 201
    return slot, response.json()["application"]


def eligible_slots(operator):
    """Application id -> slot ids it is matching-eligible for, as the operator sees it."""
    return {
        row["id"]: row["matching_eligible_slot_ids"]
        for row in operator.get("/api/admin/applications").json()["applications"]
    }


def test_payment_after_the_earliest_candidate_close_is_refused():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        _, application = submitted(
            operator, participant, "participant-01", close_in=timedelta(seconds=2)
        )
        time.sleep(2.5)
        for product in ("single", "membership_6m"):
            late = pay(participant, application["id"], product)
            assert (late.status_code, late.json()) == (409, {"detail": "payment_closed"})
        (listed,) = participant.get("/api/me/applications").json()["applications"]
        assert listed["payments"] == [] and listed["coverage"] is None
        assert participant.get("/api/me/entitlements").json()["entitlements"] == []


def test_deadline_passing_while_a_payment_waits_for_the_participant_lock_refuses_it():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        _, application = submitted(
            operator, participant, "participant-01", close_in=timedelta(seconds=2)
        )
        user_id = participant.get("/api/auth/me").json()["user"]["id"]
        connection, transaction = hold_lock(
            "SELECT id FROM app_user WHERE id = :id FOR UPDATE", {"id": user_id}
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(pay, participant, application["id"], "single")
            time.sleep(2.5)
            transaction.rollback()
            connection.close()
            response = pending.result(timeout=10)
        assert (response.status_code, response.json()) == (409, {"detail": "payment_closed"})
        (listed,) = participant.get("/api/me/applications").json()["applications"]
        assert listed["payments"] == []


def test_only_paid_or_membership_covered_applications_are_matching_eligible():
    with (
        TestClient(app) as operator,
        TestClient(app) as unpaid,
        TestClient(app) as single,
        TestClient(app) as member,
    ):
        login(operator, "operator")
        slot = create_slot(operator, days=7)
        applications = {}
        for client, login_id in (
            (unpaid, "participant-01"),
            (single, "participant-02"),
            (member, "participant-03"),
        ):
            login(client, login_id)
            make_ready(client)
            applications[login_id] = apply(client, [slot]).json()["application"]["id"]
        assert pay(single, applications["participant-02"], "single").status_code == 201
        # The membership was bought for an earlier application and covers this one.
        earlier = apply(member, [create_slot(operator, days=5)]).json()["application"]["id"]
        assert pay(member, earlier, "membership_1m").status_code == 201
        eligible = eligible_slots(operator)
        assert eligible[applications["participant-01"]] == []
        assert eligible[applications["participant-02"]] == [slot]
        assert eligible[applications["participant-03"]] == [slot]
        # The worker-facing function agrees with the operator view.
        with database_engine().connect() as connection:
            rows = matching_eligible_applications(connection, slot, locked_now(connection))
        assert {str(row["application_id"]) for row in rows} == {
            applications["participant-02"],
            applications["participant-03"],
        }


def test_membership_bought_after_a_close_does_not_cover_that_slot_retroactively():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        closed_slot, closed = submitted(
            operator, participant, "participant-01", days=10, close_in=timedelta(seconds=2)
        )
        time.sleep(2.5)
        later_slot = create_slot(operator, days=12)
        later = apply(participant, [later_slot]).json()["application"]
        # Three months from now reaches the closed slot's start too.
        assert pay(participant, later["id"], "membership_3m").status_code == 201
        eligible = eligible_slots(operator)
        assert eligible[closed["id"]] == []
        assert eligible[later["id"]] == [later_slot]
        with database_engine().connect() as connection:
            now = locked_now(connection)
            assert matching_eligible_applications(connection, closed_slot, now) == []
        # The participant view agrees: the closed application stays unpaid and excluded.
        listed = {
            row["id"]: row for row in participant.get("/api/me/applications").json()["applications"]
        }
        assert listed[closed["id"]]["coverage"] is None
        assert listed[closed["id"]]["payment_required"] is True
        assert listed[closed["id"]]["matching_eligible_slot_ids"] == []


def test_failed_payment_then_successful_retry_leaves_one_paid_and_makes_it_eligible():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        slot, application = submitted(operator, participant, "participant-01")
        failed = pay(participant, application["id"], "single", simulate_failure=True)
        assert failed.json()["payment"]["state"] == "FAILED"
        assert eligible_slots(operator)[application["id"]] == []
        assert pay(participant, application["id"], "single").status_code == 201
        again = pay(participant, application["id"], "single")
        assert (again.status_code, again.json()) == (409, {"detail": "payment_already_paid"})
        (listed,) = participant.get("/api/me/applications").json()["applications"]
        assert [item["state"] for item in listed["payments"]] == ["PAID", "FAILED"]
        assert len(participant.get("/api/me/entitlements").json()["entitlements"]) == 1
        assert eligible_slots(operator)[application["id"]] == [slot]


def test_canceling_a_paid_application_drops_its_matching_eligibility():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        slot, application = submitted(operator, participant, "participant-01")
        assert pay(participant, application["id"], "single").status_code == 201
        assert eligible_slots(operator)[application["id"]] == [slot]
        (held,) = participant.get("/api/me/entitlements").json()["entitlements"]
        assert (held["state"], held["application_state"]) == ("HELD", "SUBMITTED")
        canceled = send(participant, "POST", f"/api/me/applications/{application['id']}/cancel")
        assert canceled.json()["application"]["matching_eligible_slot_ids"] == []
        # Canceling is not a refund: the pass stays held, visibly tied to a canceled application.
        (held,) = participant.get("/api/me/entitlements").json()["entitlements"]
        assert (held["state"], held["application_state"]) == ("HELD", "CANCELED")
        assert eligible_slots(operator)[application["id"]] == []
        with database_engine().connect() as connection:
            assert matching_eligible_applications(connection, slot, locked_now(connection)) == []
