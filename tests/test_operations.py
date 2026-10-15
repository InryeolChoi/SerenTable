from fastapi.testclient import TestClient
from serentable.main import app


def test_liveness_does_not_require_database():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"
    assert "version" in response.json()


def test_readiness_rejects_unreachable_database_without_exposing_credentials(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private_user:secret@127.0.0.1:1/private_db")
    with TestClient(app) as client:
        response = client.get("/api/readiness")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}


def test_readiness_requires_reachable_postgresql(monkeypatch):
    import os

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(app) as client:
        response = client.get("/api/readiness")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "connected"}


def test_worker_records_heartbeat_visible_over_http(monkeypatch):
    import os
    import subprocess
    import sys

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    subprocess.run([sys.executable, "-m", "serentable.worker", "--once"], check=True)
    with TestClient(app) as client:
        response = client.get("/api/worker-health")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_participant_and_admin_routes_serve_built_csr_on_refresh():
    with TestClient(app) as client:
        for route in ("/", "/participant", "/admin"):
            response = client.get(route)
            assert response.status_code == 200
            assert '<div id="root"></div>' in response.text
            assert "/assets/" in response.text


def test_unknown_api_is_not_masked_by_spa_fallback():
    with TestClient(app) as client:
        assert client.get("/api/does-not-exist").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404


def test_worker_connection_failure_exits_nonzero_without_secrets(monkeypatch):
    import subprocess
    import sys

    monkeypatch.setenv("DATABASE_URL", "postgresql://private_user:secret@127.0.0.1:1/private_db")
    result = subprocess.run(
        [sys.executable, "-m", "serentable.worker", "--once"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "worker_database_unavailable" in result.stderr
    assert all(value not in result.stderr for value in ("private_user", "secret", "private_db"))
