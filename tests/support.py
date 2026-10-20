"""Helpers shared by the real-PostgreSQL HTTP tests (the fixture lives in conftest.py)."""

import time
from datetime import timedelta, timezone

ORIGIN = "http://testserver"
SEOUL = timezone(timedelta(hours=9))


def login(client, login_id="participant-01"):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    role = "operator" if login_id == "operator" else "participant"
    response = client.post(
        "/api/auth/login",
        json={"login_id": login_id, "password": f"synthetic-{role}-password"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )
    assert response.status_code == 200
    return response.json()["user"]


def send(client, method, path, payload=None):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.request(
        method, path, json=payload, headers={"Origin": ORIGIN, "X-CSRF-Token": token}
    )


def truncate(tables):
    from serentable.database import database_engine
    from sqlalchemy import text

    with database_engine().begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


def wait_for_slot_matching(slot, timeout=30):
    """Wait for the actual PG deadline; host/Docker wall clocks need not agree."""
    from serentable.database import database_engine
    from sqlalchemy import text

    deadline = time.monotonic() + timeout
    with database_engine().connect() as connection:
        while True:
            remaining = connection.execute(
                text(
                    "SELECT extract(epoch FROM matches_at-clock_timestamp()) "
                    "FROM event_slot WHERE id=:id"
                ),
                {"id": slot},
            ).scalar_one()
            if remaining <= 0:
                return
            if time.monotonic() >= deadline:
                raise AssertionError("isolated_slot_matching_deadline_not_reached")
            time.sleep(min(float(remaining), 0.25))
