"""Confirmed-table chat behavior through HTTP and the real isolated PostgreSQL."""

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
def chat_members(seeded_database):
    truncate("event_slot, participant_profile, consent_record")
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, member in enumerate(members, 1):
            prepare(member, f"participant-0{index}")
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        # Room setup is explicit until the gathering worker integration is merged.
        with database_engine().begin() as connection:
            connection.execute(
                text("""INSERT INTO chat_room(id,dining_table_id,created_at)
                SELECT :id,id,CURRENT_TIMESTAMP FROM dining_table"""),
                {"id": uuid.uuid4()},
            )
        yield operator, members


def test_confirmed_members_can_discover_their_shared_room(chat_members):
    operator, members = chat_members
    response = members[0].get("/api/me/rooms")
    assert response.status_code == 200
    (room,) = response.json()["rooms"]
    assert room["member_count"] == 4
    assert room["region_name"] == "홍대"
    assert members[1].get("/api/me/rooms").json()["rooms"] == [room]
    assert operator.get("/api/me/rooms").status_code == 403


def test_messages_persist_and_reconnect_without_duplicates_or_private_fields(chat_members):
    _, members = chat_members
    room = members[0].get("/api/me/rooms").json()["rooms"][0]["id"]
    path = f"/api/me/rooms/{room}/messages"
    body = '<img src=x onerror="window.chatXss=1"> 안녕하세요'
    payload = {"request_key": str(uuid.uuid4()), "body": body}
    posted = send(members[0], "POST", path, payload)
    assert posted.status_code == 201
    message = posted.json()["message"]
    assert message["body"] == body
    assert message["kind"] == "USER"
    assert set(message["author"]) == {"display_name"}
    repeated = send(members[0], "POST", path, payload)
    assert repeated.status_code == 200
    assert repeated.json()["message"] == message
    assert send(members[0], "POST", path, {**payload, "body": "다른 내용"}).status_code == 409
    page = members[1].get(path + "?limit=1").json()
    assert page["messages"] == [message]
    assert page["next_cursor"] == message["id"]
    assert members[1].get(path + f"?after_id={page['next_cursor']}").json() == {
        "messages": [],
        "next_cursor": message["id"],
    }
    assert all(
        secret not in str(page) for secret in ("contact", "instagram", "login_id", "user_id")
    )


def test_chat_checks_live_membership_csrf_and_input_on_every_request(chat_members):
    operator, members = chat_members
    room = members[0].get("/api/me/rooms").json()["rooms"][0]["id"]
    path = f"/api/me/rooms/{room}/messages"
    payload = {"request_key": str(uuid.uuid4()), "body": "인사"}
    assert operator.get(path).status_code == 403
    assert send(operator, "POST", path, payload).status_code == 403
    assert members[0].post(path, json=payload).status_code == 403
    for body in ("", "가" * 2001):
        assert send(members[0], "POST", path, {**payload, "body": body}).status_code == 422
    assert send(members[0], "POST", path, {**payload, "body": "가" * 2000}).status_code == 201
    for query in ("?after_id=-1", "?limit=101", "?limit=0"):
        assert members[0].get(path + query).status_code == 422
    assert members[0].get(f"/api/me/rooms/{uuid.uuid4()}/messages").status_code == 404
    user = members[0].get("/api/auth/me").json()["user"]["id"]
    with database_engine().begin() as connection:
        connection.execute(
            text("UPDATE table_assignment SET ended_at=CURRENT_TIMESTAMP WHERE user_id=:id"),
            {"id": user},
        )
    assert members[0].get("/api/me/rooms").json() == {"rooms": []}
    assert members[0].get(path).status_code == 404
    assert send(members[0], "POST", path, payload).status_code == 404
    user2 = members[1].get("/api/auth/me").json()["user"]["id"]
    with database_engine().begin() as connection:
        connection.execute(
            text(
                "UPDATE match_participation SET state='EXCEPTION',reason_code='test', "
                "dining_table_id=NULL WHERE user_id=:id"
            ),
            {"id": user2},
        )
    assert members[1].get(path).status_code == 404
    assert send(members[1], "POST", path, payload).status_code == 404


def test_concurrent_writers_do_not_skip_a_delayed_system_message(chat_members):
    from concurrent.futures import ThreadPoolExecutor

    from serentable.chat import publish_system_message

    _, members = chat_members
    room = members[0].get("/api/me/rooms").json()["rooms"][0]["id"]
    path = f"/api/me/rooms/{room}/messages"
    # Prepared DB fixture: keep the system transaction uncommitted while HTTP posts run.
    connection = database_engine().connect()
    transaction = connection.begin()
    try:
        now = connection.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
        publish_system_message(connection, room, "welcome", "함께할 식탁입니다", now)
        publish_system_message(connection, room, "welcome", "함께할 식탁입니다", now)
        tokens = [member.get("/api/auth/csrf").json()["csrf_token"] for member in members]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(
                    member.post,
                    path,
                    json={"request_key": str(uuid.uuid4()), "body": f"인사 {index}"},
                    headers={"Origin": "http://testserver", "X-CSRF-Token": token},
                )
                for index, (member, token) in enumerate(zip(members, tokens, strict=True))
            ]
            time.sleep(0.2)
            assert members[0].get(path).json()["messages"] == []
            transaction.commit()
            assert [future.result(timeout=5).status_code for future in futures] == [201] * 4
        result = members[0].get(path).json()
        assert len(result["messages"]) == 5
        assert result["messages"][0]["kind"] == "SYSTEM"
        assert result["messages"][0]["author"] is None
        ids = [message["id"] for message in result["messages"]]
        assert ids == sorted(set(ids))
        cursor = 0
        received = []
        for _ in range(3):
            page = members[0].get(path + f"?after_id={cursor}&limit=2").json()
            received.extend(page["messages"])
            cursor = page["next_cursor"]
        assert received == result["messages"]
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
