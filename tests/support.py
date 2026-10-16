"""Helpers shared by the real-PostgreSQL HTTP tests (the fixture lives in conftest.py)."""

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
