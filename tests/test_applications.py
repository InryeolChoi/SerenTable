import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from serentable.main import app

ORIGIN = "http://testserver"
SEOUL = timezone(timedelta(hours=9))


@pytest.fixture(autouse=True)
def application_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setenv("AUTH_SIGNING_KEY", "local-application-test-signing-key-1234567890")
    monkeypatch.setenv("DEMO_PARTICIPANT_PASSWORD", "synthetic-participant-password")
    monkeypatch.setenv("DEMO_OPERATOR_PASSWORD", "synthetic-operator-password")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "serentable.seed_demo_accounts"], check=True)
    from serentable.database import database_engine
    from sqlalchemy import text

    with database_engine().begin() as connection:
        connection.execute(text("TRUNCATE event_slot, participant_profile, consent_record CASCADE"))


def login(client, login_id):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    role = "operator" if login_id == "operator" else "participant"
    response = client.post(
        "/api/auth/login",
        json={"login_id": login_id, "password": f"synthetic-{role}-password"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )
    assert response.status_code == 200


def send(client, method, path, payload=None):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.request(
        method, path, json=payload, headers={"Origin": ORIGIN, "X-CSRF-Token": token}
    )


def create_slot(operator, days=7, region="hongdae", close_in=timedelta(days=3)):
    start = (datetime.now(SEOUL) + timedelta(days=days)).replace(
        hour=19, minute=0, second=0, microsecond=0
    )
    closes = datetime.now(SEOUL) + close_in
    response = send(
        operator,
        "POST",
        "/api/admin/event-slots",
        {
            "region_code": region,
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=2)).isoformat(),
            "closes_at": closes.isoformat(),
            "matches_at": max(closes, start - timedelta(days=1)).isoformat(),
            "capacity": 24,
        },
    )
    assert response.status_code == 201
    return response.json()["event_slot"]["id"]


COMPLETE_PROFILE = {
    "name": "합성 이름",
    "display_name": "테스트 식탁",
    "contact": "010-0000-0000",
    "instagram_id": "synthetic_demo",
    "birth_year": 1995,
    "gender": "기록한 성별",
    "occupation": "합성 직업",
    "interests": ["reading"],
    "self_traits": ["listener"],
    "desired_traits": ["different"],
    "meal_budget_bands": ["10000_20000"],
}


def make_ready(participant, profile=True, consents=True):
    if profile:
        assert send(participant, "PUT", "/api/me/profile", COMPLETE_PROFILE).status_code == 200
    if consents:
        decisions = [
            {"purpose": purpose, "version": "demo-2026-10-16", "accepted": True}
            for purpose in ("privacy", "operation")
        ]
        response = send(participant, "PUT", "/api/me/consents", {"consents": decisions})
        assert response.json()["complete"] is True


def apply(participant, slot_ids, key=None):
    return send(
        participant,
        "POST",
        "/api/me/applications",
        {"request_key": key or str(uuid.uuid4()), "event_slot_ids": slot_ids},
    )


def test_participant_submits_explicit_candidates_and_sees_own_status():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        hongdae = create_slot(operator, days=7, region="hongdae")
        gangnam = create_slot(operator, days=8, region="gangnam")
        create_slot(operator, days=9, region="jamsil")
        login(participant, "participant-01")
        make_ready(participant)
        created = apply(participant, [gangnam, hongdae])
        assert created.status_code == 201
        assert created.headers["cache-control"] == "no-store"
        body = created.json()["application"]
        assert body["state"] == "SUBMITTED"
        # Only the chosen slots are kept, ordered by start time; nothing is derived.
        assert [item["id"] for item in body["candidates"]] == [hongdae, gangnam]
        assert body["candidates"][1]["region"] == {"code": "gangnam", "name": "강남"}
        # Submission is not payment: nothing is paid yet and a pass is still required.
        assert body["payments"] == [] and body["payment_required"] is True
        assert body["canceled_at"] is None
        listed = participant.get("/api/me/applications")
        assert listed.status_code == 200
        assert listed.json()["applications"] == [body]


def test_submission_requires_complete_profile_consents_and_recruiting_candidates():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        open_slot = create_slot(operator, days=7)
        closing = create_slot(operator, days=8, close_in=timedelta(seconds=1))
        login(participant, "participant-01")
        missing_profile = apply(participant, [open_slot])
        assert (missing_profile.status_code, missing_profile.json()) == (
            409,
            {"detail": "profile_incomplete"},
        )
        make_ready(participant, profile=True, consents=False)
        no_consent = apply(participant, [open_slot])
        assert (no_consent.status_code, no_consent.json()) == (
            409,
            {"detail": "consent_incomplete"},
        )
        make_ready(participant, profile=False, consents=True)
        time.sleep(1.5)
        for slot_ids in ([open_slot, closing], [open_slot, str(uuid.uuid4())]):
            rejected = apply(participant, slot_ids)
            assert rejected.status_code == 422, slot_ids
            assert rejected.json()["detail"][0]["loc"] == ["body", "event_slot_ids"]
        for payload in (
            {"request_key": str(uuid.uuid4()), "event_slot_ids": []},
            {"request_key": str(uuid.uuid4()), "event_slot_ids": [open_slot, open_slot]},
            {"request_key": "not-a-uuid", "event_slot_ids": [open_slot]},
            {"event_slot_ids": [open_slot]},
            {"request_key": str(uuid.uuid4()), "event_slot_ids": [open_slot], "paid": True},
        ):
            assert send(participant, "POST", "/api/me/applications", payload).status_code == 422
        # Rejections leave nothing behind.
        assert participant.get("/api/me/applications").json()["applications"] == []
        assert apply(participant, [open_slot]).status_code == 201


def test_resubmitted_request_returns_same_result_and_live_slot_cannot_be_held_twice():
    with TestClient(app) as operator, TestClient(app) as one, TestClient(app) as two:
        login(operator, "operator")
        first = create_slot(operator, days=7)
        second = create_slot(operator, days=8)
        third = create_slot(operator, days=9)
        login(one, "participant-01")
        make_ready(one)
        key = str(uuid.uuid4())
        created = apply(one, [first, second], key)
        assert created.status_code == 201
        replay = apply(one, [second, first], key)
        assert (replay.status_code, replay.json()) == (200, created.json())
        reused = apply(one, [third], key)
        assert (reused.status_code, reused.json()) == (409, {"detail": "request_key_reused"})
        overlap = apply(one, [second, third])
        assert (overlap.status_code, overlap.json()) == (
            409,
            {"detail": "application_slot_duplicate"},
        )
        assert apply(one, [third]).status_code == 201
        assert len(one.get("/api/me/applications").json()["applications"]) == 2
        # Another participant's applications are independent and invisible to the first.
        login(two, "participant-02")
        make_ready(two)
        assert apply(two, [first], key).status_code == 201
        assert len(two.get("/api/me/applications").json()["applications"]) == 1
        assert len(one.get("/api/me/applications").json()["applications"]) == 2


def test_concurrent_submits_create_exactly_one_application():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        slot_a = create_slot(operator, days=7)
        slot_b = create_slot(operator, days=8)
        login(participant, "participant-01")
        make_ready(participant)
        token = participant.get("/api/auth/csrf").json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": token}

        def submit(body):
            return participant.post("/api/me/applications", json=body, headers=headers)

        same = {"request_key": str(uuid.uuid4()), "event_slot_ids": [slot_a]}
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, [same] * 6))
        assert sorted(r.status_code for r in responses) == [200] * 5 + [201]
        assert len({r.json()["application"]["id"] for r in responses}) == 1
        distinct = [
            {"request_key": str(uuid.uuid4()), "event_slot_ids": [slot_b]} for _ in range(6)
        ]
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, distinct))
        assert sorted(r.status_code for r in responses) == [201] + [409] * 5
        assert len(participant.get("/api/me/applications").json()["applications"]) == 2


def test_owner_cancels_before_earliest_close_and_may_then_reapply():
    with TestClient(app) as operator, TestClient(app) as one, TestClient(app) as two:
        login(operator, "operator")
        later = create_slot(operator, days=7)
        soon = create_slot(operator, days=8, close_in=timedelta(seconds=2))
        login(one, "participant-01")
        login(two, "participant-02")
        make_ready(one)
        make_ready(two)
        application = apply(one, [later]).json()["application"]
        path = f"/api/me/applications/{application['id']}/cancel"
        assert send(two, "POST", path).status_code == 404
        canceled = send(one, "POST", path)
        assert canceled.status_code == 200
        body = canceled.json()["application"]
        assert body["state"] == "CANCELED" and body["canceled_at"] is not None
        assert send(one, "POST", path).json() == canceled.json()
        assert apply(one, [later]).status_code == 201
        closing = apply(one, [soon]).json()["application"]
        time.sleep(2.5)
        late = send(one, "POST", f"/api/me/applications/{closing['id']}/cancel")
        assert (late.status_code, late.json()) == (409, {"detail": "application_cancel_closed"})
        states = [item["state"] for item in one.get("/api/me/applications").json()["applications"]]
        assert sorted(states) == ["CANCELED", "SUBMITTED", "SUBMITTED"]
        assert send(one, "POST", f"/api/me/applications/{uuid.uuid4()}/cancel").status_code == 404


def test_operator_reads_all_applications_and_roles_are_enforced():
    with (
        TestClient(app) as anonymous,
        TestClient(app) as operator,
        TestClient(app) as one,
        TestClient(app) as two,
    ):
        login(operator, "operator")
        slot = create_slot(operator, days=7)
        for client, login_id in ((one, "participant-01"), (two, "participant-02")):
            login(client, login_id)
            make_ready(client)
            assert apply(client, [slot]).status_code == 201
        listed = operator.get("/api/admin/applications")
        assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
        rows = listed.json()["applications"]
        assert sorted(row["participant"]["login_id"] for row in rows) == [
            "participant-01",
            "participant-02",
        ]
        assert all(row["candidates"][0]["id"] == slot for row in rows)
        assert len(one.get("/api/me/applications").json()["applications"]) == 1
        assert one.get("/api/admin/applications").status_code == 403
        assert operator.get("/api/me/applications").status_code == 403
        assert apply(operator, [slot]).status_code == 403
        assert anonymous.get("/api/me/applications").status_code == 401
        assert anonymous.get("/api/admin/applications").status_code == 401
        assert apply(anonymous, [slot]).status_code == 401
        no_csrf = one.post("/api/me/applications", json={"event_slot_ids": "bad"})
        assert no_csrf.status_code == 403
        cancel_path = f"/api/me/applications/{rows[0]['id']}/cancel"
        assert one.post(cancel_path).status_code == 403
