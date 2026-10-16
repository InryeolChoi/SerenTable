from fastapi.testclient import TestClient
from serentable.main import app


def test_csrf_bootstrap_returns_token_and_private_cookie(monkeypatch):
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("AUTH_SIGNING_KEY", "local-test-signing-key-never-deploy-123456789")
    with TestClient(app) as client:
        response = client.get("/api/auth/csrf")
        assert response.status_code == 200
        assert response.json()["csrf_token"]
        assert response.headers["cache-control"] == "no-store"
        assert "HttpOnly" in response.headers["set-cookie"]


def test_seeded_participant_can_log_in_and_reload_session(monkeypatch):
    import os
    import subprocess
    import sys

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("AUTH_SIGNING_KEY", "local-test-signing-key-never-deploy-123456789")
    monkeypatch.setenv("DEMO_PARTICIPANT_PASSWORD", "synthetic-participant-password")
    monkeypatch.setenv("DEMO_OPERATOR_PASSWORD", "synthetic-operator-password")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "serentable.seed_demo_accounts"], check=True)
    with TestClient(app) as client:
        token = client.get("/api/auth/csrf").json()["csrf_token"]
        response = client.post(
            "/api/auth/login",
            json={"login_id": "participant-01", "password": "synthetic-participant-password"},
            headers={"Origin": "http://testserver", "X-CSRF-Token": token},
        )
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "participant"
        assert response.json()["user"]["login_id"] == "participant-01"
        assert set(response.json()["user"]) == {"id", "login_id", "role"}
        assert client.get("/api/auth/me").json() == response.json()
