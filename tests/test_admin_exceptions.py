"""Work #9 ticket B: one operator list of open exceptions and recorded resolutions.

Exceptions are produced through the real matching and gathering worker paths on the
isolated PostgreSQL; nothing here inserts an exception row by hand.
"""

import time
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from support import login, send, truncate

PATH = "/api/admin/exceptions"


@pytest.fixture(autouse=True)
def exceptions_database(seeded_database):
    truncate(
        "event_slot, participant_profile, consent_record, app_notification, "
        "gathering_exception, operator_audit"
    )


def venue_shortage(stack):
    """Four confirmed members, no registered inventory: the worker opens one venue exception."""
    from serentable.gatherings import run_gathering_jobs
    from serentable.matching import run_due_matches
    from test_matching_runner import apply_and_pay, due_slot, prepare

    operator = stack.enter_context(TestClient(app))
    members = [stack.enter_context(TestClient(app)) for _ in range(4)]
    login(operator, "operator")
    for i, member in enumerate(members, 1):
        prepare(member, f"participant-0{i}")
    slot = due_slot(operator, close_in=4)
    for member in members:
        apply_and_pay(member, slot)
    time.sleep(4.6)
    assert run_due_matches()[0]["seated_count"] == 4
    run_gathering_jobs()
    return operator, members, slot


def test_worker_venue_shortage_is_listed_as_an_open_exception():
    with ExitStack() as stack:
        operator, _, slot = venue_shortage(stack)
        response = operator.get(PATH, params={"state": "OPEN"})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        items = response.json()["exceptions"]
        assert len(items) == 1
        item = items[0]
        assert item["kind"] == "gathering"
        assert item["category"] == "VENUE"
        assert item["event_slot_id"] == slot
        assert item["reason_code"] == "no_verified_inventory"
        assert item["state"] == "OPEN"
        assert item["occurred_at"]
        assert item["resolution_note"] is None


def audit_rows(target_id):
    """Ticket C owns the audit read API; until it lands the row is read at the fixture level."""
    from serentable.database import database_engine
    from sqlalchemy import text

    with database_engine().connect() as connection:
        return (
            connection.execute(
                text("""SELECT actor_id::text actor, action, target_type, reason,
                before_state, after_state FROM operator_audit WHERE target_id=:id"""),
                {"id": target_id},
            )
            .mappings()
            .all()
        )


def test_operator_resolution_is_recorded_once_and_does_not_rerun_the_gathering():
    with ExitStack() as stack:
        operator, members, _ = venue_shortage(stack)
        me = operator.get("/api/auth/me").json()["user"]
        (item,) = operator.get(PATH, params={"state": "OPEN"}).json()["exceptions"]
        gathering = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        path = f"/api/me/rooms/{gathering['room_id']}/messages"
        messages = members[0].get(path).json()["messages"]
        resolve = f"{PATH}/gathering/{item['id']}/resolve"
        note = "식당과 전화로 확인 후 수동 안내함"

        assert members[0].get(PATH).status_code == 403
        assert send(members[0], "POST", resolve, {"note": note}).status_code == 403
        assert operator.post(resolve, json={"note": note}).status_code == 403  # no CSRF
        assert send(operator, "POST", resolve, {"note": ""}).status_code == 422
        assert send(operator, "POST", resolve, {"note": "가" * 501}).status_code == 422
        assert operator.get(PATH, params={"state": "OPEN"}).json()["exceptions"] == [item]

        first = send(operator, "POST", resolve, {"note": note})
        assert first.status_code == 200, first.text
        resolved = first.json()["exception"]
        assert resolved["state"] == "RESOLVED"
        assert resolved["resolution_note"] == note
        assert resolved["resolved_by"] == me["id"]
        again = send(operator, "POST", resolve, {"note": note})
        assert again.status_code == 200
        assert again.json() == first.json()
        assert send(operator, "POST", resolve, {"note": "다른 메모"}).status_code == 409

        assert operator.get(PATH, params={"state": "OPEN"}).json()["exceptions"] == []
        assert operator.get(PATH, params={"state": "RESOLVED"}).json()["exceptions"] == [resolved]
        (audit,) = audit_rows(item["id"])
        assert audit["actor"] == me["id"]
        assert audit["target_type"] == "gathering_exception"
        assert audit["reason"] == note
        assert audit["before_state"] == {"state": "OPEN"}
        assert audit["after_state"] == {"state": "RESOLVED"}

        # Recording only: the gathering is not re-run, allocated or re-announced.
        mine = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        assert mine["venue_state"] == "PENDING_OPERATOR"
        assert members[0].get(path).json()["messages"] == messages


def test_a_failed_audit_write_leaves_the_exception_open():
    from serentable.database import database_engine
    from sqlalchemy import text

    with ExitStack() as stack:
        operator, _, _ = venue_shortage(stack)
        (item,) = operator.get(PATH, params={"state": "OPEN"}).json()["exceptions"]
        resolve = f"{PATH}/gathering/{item['id']}/resolve"
        # The approved storage-fault seam: the database rejects the audit row.
        with database_engine().begin() as c:
            c.execute(
                text("""CREATE FUNCTION exceptions_test_fail() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$""")
            )
            c.execute(
                text("""CREATE TRIGGER exceptions_test_fault BEFORE INSERT ON operator_audit
                FOR EACH ROW EXECUTE FUNCTION exceptions_test_fail()""")
            )
        try:
            failed = send(operator, "POST", resolve, {"note": "확인"})
            assert failed.status_code == 503
            assert failed.json()["detail"] == "exception_resolution_unavailable"
        finally:
            with database_engine().begin() as c:
                c.execute(text("DROP TRIGGER exceptions_test_fault ON operator_audit"))
                c.execute(text("DROP FUNCTION exceptions_test_fail()"))
        assert operator.get(PATH, params={"state": "OPEN"}).json()["exceptions"] == [item]
        assert audit_rows(item["id"]) == []
        # The same request succeeds once storage recovers.
        assert send(operator, "POST", resolve, {"note": "확인"}).status_code == 200


def test_an_unanswered_alternative_offer_is_listed_once_its_slot_has_started():
    from serentable.database import database_engine
    from serentable.matching import run_slot_matching
    from sqlalchemy import text
    from test_matching_runner import apply_and_pay, due_slot, prepare

    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        prepare(participant, "participant-01")
        slot = due_slot(operator)
        application_id = apply_and_pay(participant, slot)
        time.sleep(3.6)
        assert run_slot_matching(slot)["seated_count"] == 0  # one person cannot form a table
        listed = participant.get("/api/me/applications").json()["applications"]
        assert listed[0]["matching"]["state"] == "ALTERNATIVE_OFFERED"
        # Still answerable before the event: not an operator exception yet.
        assert operator.get(PATH, params={"state": "OPEN"}).json()["exceptions"] == []

        # Fixture clock moves the isolated slot past its start; no production clock override.
        with database_engine().begin() as c:
            c.execute(
                text("""UPDATE event_slot SET closes_at=now()-interval '3 minutes',
                matches_at=now()-interval '2 minutes', starts_at=now()-interval '1 minute',
                ends_at=now()+interval '1 hour' WHERE id=:slot"""),
                {"slot": slot},
            )
        before = participant.get("/api/me/applications").json()
        (item,) = operator.get(PATH, params={"state": "OPEN"}).json()["exceptions"]
        assert item["kind"] == "alternative_overdue"
        assert item["id"] == application_id
        assert item["event_slot_id"] == slot
        assert item["state"] == "OPEN"
        assert item["reason_code"] == "not_enough_eligible"
        assert item["occurred_at"]
        assert item["resolvable"] is False
        assert operator.get(PATH, params={"state": "RESOLVED"}).json()["exceptions"] == []

        # No resolution store exists for this kind; refusing keeps the participant's choice.
        resolve = f"{PATH}/alternative_overdue/{application_id}/resolve"
        refused = send(operator, "POST", resolve, {"note": "확인"})
        assert refused.status_code == 409
        assert participant.get("/api/me/applications").json() == before


def test_unknown_exception_is_not_found():
    import uuid

    with TestClient(app) as operator:
        login(operator, "operator")
        missing = f"{PATH}/gathering/{uuid.uuid4()}/resolve"
        assert send(operator, "POST", missing, {"note": "확인"}).status_code == 404
        unknown_kind = f"{PATH}/other/{uuid.uuid4()}/resolve"
        assert send(operator, "POST", unknown_kind, {"note": "확인"}).status_code == 404
