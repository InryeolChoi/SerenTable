import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from serentable.main import app

ORIGIN = "http://testserver"


@pytest.fixture(autouse=True)
def slot_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setenv("AUTH_SIGNING_KEY", "local-slot-test-signing-key-1234567890")
    monkeypatch.setenv("DEMO_PARTICIPANT_PASSWORD", "synthetic-participant-password")
    monkeypatch.setenv("DEMO_OPERATOR_PASSWORD", "synthetic-operator-password")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "serentable.seed_demo_accounts"], check=True)
    from serentable.database import database_engine
    from sqlalchemy import text

    with database_engine().begin() as connection:
        connection.execute(text("DELETE FROM event_slot"))


def login(client, login_id):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    role = "operator" if login_id == "operator" else "participant"
    response = client.post(
        "/api/auth/login",
        json={"login_id": login_id, "password": f"synthetic-{role}-password"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )
    assert response.status_code == 200


def post_slot(client, payload):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(
        "/api/admin/event-slots",
        json=payload,
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )


def slot(days=7, region="hongdae", close_in=timedelta(days=3), **changes):
    seoul = timezone(timedelta(hours=9))
    start = (datetime.now(seoul) + timedelta(days=days)).replace(
        hour=19, minute=0, second=0, microsecond=0
    )
    closes = datetime.now(seoul) + close_in
    payload = {
        "region_code": region,
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=2)).isoformat(),
        "closes_at": closes.isoformat(),
        "matches_at": max(closes, start - timedelta(days=1)).isoformat(),
        "capacity": 24,
    }
    return payload | changes


def test_operator_creates_slot_and_participant_sees_it_in_seoul_time():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        regions = operator.get("/api/admin/regions").json()["regions"]
        assert [region["name"] for region in regions] == ["홍대", "잠실", "강남", "을지로"]
        created = post_slot(operator, slot(region="jamsil"))
        assert created.status_code == 201
        body = created.json()["event_slot"]
        assert body["region"] == {"code": "jamsil", "name": "잠실"}
        assert body["starts_at"].endswith("+09:00") and "T19:00:00" in body["starts_at"]
        assert body["recruiting"] is True and body["capacity"] == 24
        assert created.headers["cache-control"] == "no-store"
        assert operator.get("/api/admin/event-slots").json()["event_slots"] == [body]
        login(participant, "participant-01")
        assert participant.get("/api/event-slots").json()["event_slots"] == [body]


def test_slot_input_is_validated_without_partial_writes():
    with TestClient(app) as operator:
        login(operator, "operator")
        base = slot()
        invalid = [
            {**base, "ends_at": base["starts_at"]},
            {**base, "matches_at": base["starts_at"].replace("T19", "T20")},
            {**base, "closes_at": base["ends_at"]},
            {**base, "capacity": 3},
            {**base, "capacity": 101},
            {**base, "capacity": "24"},
            {**base, "starts_at": base["starts_at"][:19]},
            {**base, "unexpected": True},
        ]
        for payload in invalid:
            assert post_slot(operator, payload).status_code == 422, payload
        unknown = post_slot(operator, slot(region="busan"))
        assert unknown.status_code == 422
        assert unknown.json()["detail"][0]["loc"] == ["body", "region_code"]
        past = post_slot(operator, slot(close_in=timedelta(minutes=-1)))
        assert past.status_code == 422
        assert past.json()["detail"][0]["loc"] == ["body", "closes_at"]
        assert operator.get("/api/admin/event-slots").json()["event_slots"] == []


def test_duplicate_region_start_is_rejected_even_when_concurrent():
    with TestClient(app) as operator:
        login(operator, "operator")
        payload = slot(region="gangnam")
        token = operator.get("/api/auth/csrf").json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": token}

        def submit(_):
            return operator.post("/api/admin/event-slots", json=payload, headers=headers)

        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = sorted(response.status_code for response in pool.map(submit, range(4)))
        assert statuses == [201, 409, 409, 409]
        assert len(operator.get("/api/admin/event-slots").json()["event_slots"]) == 1
        assert post_slot(operator, slot(region="euljiro")).status_code == 201


def test_only_operators_manage_slots_and_only_participants_browse_open_ones():
    with TestClient(app) as anonymous, TestClient(app) as participant, TestClient(app) as op:
        assert anonymous.get("/api/event-slots").status_code == 401
        assert anonymous.get("/api/admin/event-slots").status_code == 401
        assert post_slot(anonymous, slot()).status_code == 401
        login(participant, "participant-01")
        assert participant.get("/api/admin/event-slots").status_code == 403
        assert participant.get("/api/admin/regions").status_code == 403
        assert post_slot(participant, slot()).status_code == 403
        login(op, "operator")
        assert op.get("/api/event-slots").status_code == 403
        no_csrf = op.post("/api/admin/event-slots", json={"capacity": "bad"})
        assert no_csrf.status_code == 403


def test_closed_slot_leaves_participant_list_but_stays_for_operator():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        login(participant, "participant-01")
        closing = post_slot(operator, slot(close_in=timedelta(seconds=2), days=8))
        open_slot = post_slot(operator, slot(days=9))
        assert closing.status_code == 201 and open_slot.status_code == 201
        assert len(participant.get("/api/event-slots").json()["event_slots"]) == 2
        time.sleep(2.5)
        visible = participant.get("/api/event-slots").json()["event_slots"]
        assert [item["id"] for item in visible] == [open_slot.json()["event_slot"]["id"]]
        listed = operator.get("/api/admin/event-slots").json()["event_slots"]
        assert [item["recruiting"] for item in listed] == [False, True]
