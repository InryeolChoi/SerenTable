"""Work #8 T1 check-in and no-show review through HTTP and the real isolated PostgreSQL."""

import time
import uuid
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from serentable.matching import run_due_matches
from sqlalchemy import text
from support import login, send, truncate
from test_matching_runner import apply_and_pay, due_slot, prepare


@pytest.fixture
def table(seeded_database):
    """Four confirmed members at one table, plus an operator and an outsider."""
    truncate("event_slot, participant_profile, consent_record")
    # A synthetic participant who never joins the table (same demo password hash).
    with database_engine().begin() as connection:
        connection.execute(
            text("""INSERT INTO app_user(id,login_id,password_hash,role,active)
            SELECT gen_random_uuid(),'participant-t1-outsider',password_hash,role,true
            FROM app_user WHERE login_id='participant-01' ON CONFLICT(login_id) DO NOTHING""")
        )
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        outsider = stack.enter_context(TestClient(app))
        login(operator, "operator")
        login(outsider, "participant-t1-outsider")
        for index, member in enumerate(members, 1):
            prepare(member, f"participant-0{index}")
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        with database_engine().connect() as connection:
            table_id = str(connection.execute(text("SELECT id FROM dining_table")).scalar_one())
        yield {
            "slot": slot,
            "table": table_id,
            "operator": operator,
            "members": members,
            "outsider": outsider,
        }


def move_slot(slot, starts_in, ends_in):
    """Fixture clock: shift the isolated slot relative to the DB clock (no app overrides)."""
    with database_engine().begin() as connection:
        connection.execute(
            text("""UPDATE event_slot SET closes_at=now()+(:s||' minutes')::interval
                -interval '2 days', matches_at=now()+(:s||' minutes')::interval-interval '1 day',
                starts_at=now()+(:s||' minutes')::interval,
                ends_at=now()+(:e||' minutes')::interval WHERE id=:slot"""),
            {"s": str(starts_in), "e": str(ends_in), "slot": slot},
        )


def user_id(client):
    return client.get("/api/auth/me").json()["user"]["id"]


def check_in(client, table_id):
    return send(client, "POST", f"/api/me/tables/{table_id}/check-in")


def test_check_in_opens_30_minutes_before_start_and_closes_at_the_end(table):
    member = table["members"][0]
    move_slot(table["slot"], starts_in=31, ends_in=151)
    closed = check_in(member, table["table"])
    assert closed.status_code == 409
    assert closed.json()["detail"] == "check_in_closed"
    move_slot(table["slot"], starts_in=29, ends_in=149)
    opened = check_in(member, table["table"])
    assert opened.status_code == 201, opened.text
    state = opened.json()["check_in"]
    assert state["table_id"] == table["table"]
    assert state["checked_in_at"]
    again = check_in(member, table["table"])
    assert again.status_code == 200
    assert again.json()["check_in"] == state
    # After the end a new check-in is refused, but a stored one is still reported as-is.
    move_slot(table["slot"], starts_in=-150, ends_in=-1)
    assert check_in(member, table["table"]).json() == {"check_in": state}
    late = check_in(table["members"][1], table["table"])
    assert late.status_code == 409
    assert late.json()["detail"] == "check_in_closed"


def test_check_in_is_only_for_live_confirmed_members_with_csrf(table):
    move_slot(table["slot"], starts_in=10, ends_in=130)
    path = f"/api/me/tables/{table['table']}/check-in"
    assert check_in(table["outsider"], table["table"]).status_code == 404
    assert check_in(table["members"][0], str(uuid.uuid4())).status_code == 404
    assert check_in(table["operator"], table["table"]).status_code == 403
    assert table["members"][0].post(path).status_code == 403
    member = table["members"][1]
    with database_engine().begin() as connection:
        connection.execute(
            text("UPDATE table_assignment SET ended_at=now() WHERE user_id=:id"),
            {"id": user_id(member)},
        )
    assert check_in(member, table["table"]).status_code == 404


def test_operator_reviews_unchecked_confirmed_members_once_after_the_end(table):
    operator, members = table["operator"], table["members"]
    move_slot(table["slot"], starts_in=10, ends_in=130)
    assert check_in(members[0], table["table"]).status_code == 201
    path = "/api/admin/no-show-candidates"
    # Before the end nobody is a candidate yet, and a review is refused.
    assert operator.get(path).json() == {"candidates": []}
    absent = user_id(members[1])
    early = send(operator, "POST", f"{path}/{table['table']}/{absent}", {"decision": "EXCUSED"})
    assert early.status_code == 404
    move_slot(table["slot"], starts_in=-130, ends_in=-10)
    candidates = operator.get(path).json()["candidates"]
    expected = sorted(user_id(member) for member in members[1:])
    assert sorted(item["user_id"] for item in candidates) == expected
    assert {item["table_id"] for item in candidates} == {table["table"]}
    assert all(item["display_name"] and item["region_name"] for item in candidates)
    assert all(
        secret not in str(candidates) for secret in ("contact", "instagram", "login_id", "phone")
    )
    # Participants cannot read or write the review queue; writes need CSRF.
    assert members[1].get(path).status_code == 403
    review = f"{path}/{table['table']}/{absent}"
    assert send(members[1], "POST", review, {"decision": "EXCUSED"}).status_code == 403
    assert operator.post(review, json={"decision": "EXCUSED"}).status_code == 403
    assert send(operator, "POST", review, {"decision": "LATE"}).status_code == 422
    # A checked-in member is not a candidate and cannot be marked.
    checked = f"{path}/{table['table']}/{user_id(members[0])}"
    confirmed = {"decision": "CONFIRMED_NO_SHOW"}
    assert send(operator, "POST", checked, confirmed).status_code == 404
    first = send(operator, "POST", review, confirmed)
    assert first.status_code == 201, first.text
    stored = first.json()["review"]
    assert stored["decision"] == "CONFIRMED_NO_SHOW"
    repeated = send(operator, "POST", review, confirmed)
    assert repeated.status_code == 200
    assert repeated.json()["review"] == stored
    changed = send(operator, "POST", review, {"decision": "EXCUSED"})
    assert changed.status_code == 409
    assert changed.json()["detail"] == "no_show_already_reviewed"
    remaining = [item["user_id"] for item in operator.get(path).json()["candidates"]]
    assert absent not in remaining and len(remaining) == 2
    excused = f"{path}/{table['table']}/{user_id(members[2])}"
    assert send(operator, "POST", excused, {"decision": "EXCUSED"}).status_code == 201
    # A late check-in attempt after the end cannot clear a candidate.
    assert check_in(members[3], table["table"]).status_code == 409
    assert [item["user_id"] for item in operator.get(path).json()["candidates"]] == [
        user_id(members[3])
    ]
