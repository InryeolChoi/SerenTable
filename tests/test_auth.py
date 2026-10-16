import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from sqlalchemy import create_engine, text

ORIGIN = "http://testserver"
KEY = "local-test-signing-key-never-deploy-123456789"
PARTICIPANT_PASSWORD = "synthetic-participant-password"
OPERATOR_PASSWORD = "synthetic-operator-password"


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setenv("AUTH_SIGNING_KEY", KEY)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    monkeypatch.delenv("AUTH_SESSION_TTL_SECONDS", raising=False)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("DEMO_PARTICIPANT_PASSWORD", PARTICIPANT_PASSWORD)
    monkeypatch.setenv("DEMO_OPERATOR_PASSWORD", OPERATOR_PASSWORD)


@pytest.fixture
def seeded_accounts(auth_env):
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    result = subprocess.run(
        [sys.executable, "-m", "serentable.seed_demo_accounts"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert PARTICIPANT_PASSWORD not in result.stdout + result.stderr
    assert OPERATOR_PASSWORD not in result.stdout + result.stderr
    engine = create_engine(
        os.environ["TEST_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
    )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_login_limit"))
    engine.dispose()


@pytest.fixture
def client(seeded_accounts):
    with TestClient(app) as value:
        yield value


def csrf_headers(client):
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def sign_in(client, login_id="participant-01", password=PARTICIPANT_PASSWORD):
    return client.post(
        "/api/auth/login",
        headers=csrf_headers(client),
        json={"login_id": login_id, "password": password},
    )


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


def test_auth_boundary_hides_configuration_and_database_failure(monkeypatch):
    monkeypatch.delenv("AUTH_SIGNING_KEY", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/auth/csrf")
        assert response.status_code == 503
        assert response.headers.get("cache-control") == "no-store"
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("AUTH_SIGNING_KEY", "local-test-signing-key-never-deploy-123456789")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://secret_user:private_password@127.0.0.1:1/private_db"
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("dev-serentable_session", "untrusted-value")
        response = client.get("/api/auth/me")
        assert response.status_code == 503
        assert response.json() == {"detail": "auth_storage_unavailable"}
        assert response.headers.get("cache-control") == "no-store"
        assert "private" not in response.text
    monkeypatch.delenv("DATABASE_URL")
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("dev-serentable_session", "untrusted-value")
        response = client.get("/api/auth/me")
        assert response.status_code == 503
        assert response.json() == {"detail": "auth_storage_unavailable"}


def test_invalid_login_payload_does_not_echo_secret(client):
    secret = "never-echo-secret-" * 10
    response = client.post(
        "/api/auth/login",
        json={"login_id": "participant-01", "password": secret},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert "input" not in response.text


def test_login_rejects_credentials_without_disclosing_account_presence(client):
    unknown = sign_in(client, login_id="not-a-demo-account", password="wrong-password")
    known = sign_in(client, password="wrong-password")
    assert unknown.status_code == known.status_code == 401
    assert unknown.json() == known.json() == {"detail": "invalid_credentials"}
    assert client.get("/api/auth/me").status_code == 401


def test_session_role_and_logout_are_enforced_by_server(client):
    result = sign_in(client)
    assert result.status_code == 200
    captured_session = client.cookies.get("dev-serentable_session")
    assert client.get("/api/admin/session").status_code == 403
    # Updating browser-controlled role/id values never creates operator authority.
    rejected = client.post(
        "/api/auth/login",
        headers=csrf_headers(client),
        json={
            "login_id": "participant-01",
            "password": PARTICIPANT_PASSWORD,
            "role": "operator",
            "id": "not-the-owner",
        },
    )
    assert rejected.status_code == 422
    assert client.get("/api/admin/session").status_code == 403
    assert client.post("/api/auth/logout", headers=csrf_headers(client)).json() == {
        "status": "logged_out"
    }
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set("dev-serentable_session", captured_session)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.clear()
    assert sign_in(client, login_id="operator", password=OPERATOR_PASSWORD).status_code == 200
    assert client.get("/api/admin/session").json()["user"]["role"] == "operator"


def test_csrf_rejects_foreign_origin_missing_tampered_and_wrong_session_tokens(client):
    headers = csrf_headers(client)
    credentials = {"login_id": "participant-01", "password": PARTICIPANT_PASSWORD}
    for invalid in (
        {},
        {"Origin": ORIGIN},
        {"Origin": "https://foreign.invalid", "X-CSRF-Token": headers["X-CSRF-Token"]},
        {"Origin": "null", "X-CSRF-Token": headers["X-CSRF-Token"]},
        {"Origin": ORIGIN, "X-CSRF-Token": headers["X-CSRF-Token"] + "bad"},
    ):
        assert client.post("/api/auth/login", headers=invalid, json=credentials).status_code == 403
    assert client.post("/api/auth/login", headers=headers, json=credentials).status_code == 200
    # The pre-login token cannot authorize a post-login session's mutations.
    assert client.post("/api/auth/logout", headers=headers).status_code == 403
    valid = csrf_headers(client)
    with TestClient(app) as other:
        other_headers = csrf_headers(other)
        assert sign_in(other, login_id="participant-02").status_code == 200
        other_headers = csrf_headers(other)
        mixed = {"Origin": ORIGIN, "X-CSRF-Token": other_headers["X-CSRF-Token"]}
        assert client.post("/api/auth/logout", headers=mixed).status_code == 403
    # A second tab/bootstrap does not rotate the nonce and invalidate the first tab.
    csrf_headers(client)
    assert client.post("/api/auth/logout", headers=valid).status_code == 200


def test_login_rotation_revokes_previous_cookie(client):
    assert sign_in(client).status_code == 200
    before = client.cookies.get("dev-serentable_session")
    assert sign_in(client).status_code == 200
    after = client.cookies.get("dev-serentable_session")
    assert after != before
    with TestClient(app) as replay:
        replay.cookies.set("dev-serentable_session", before)
        assert replay.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200


def test_secure_production_cookie_and_missing_key_fail_closed(seeded_accounts, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_ORIGIN", "https://testserver")
    with TestClient(app, base_url="https://testserver") as secure:
        bootstrap = secure.get("/api/auth/csrf")
        assert bootstrap.status_code == 200
        headers = {"Origin": "https://testserver", "X-CSRF-Token": bootstrap.json()["csrf_token"]}
        response = secure.post(
            "/api/auth/login",
            headers=headers,
            json={"login_id": "participant-01", "password": PARTICIPANT_PASSWORD},
        )
        assert response.status_code == 200
        cookie_headers = response.headers.get_list("set-cookie")
        assert any("__Host-serentable_session=" in value for value in cookie_headers)
        for value in cookie_headers:
            assert "Secure" in value and "HttpOnly" in value and "SameSite=lax" in value
            assert "Path=/" in value and "Domain=" not in value and "Max-Age" not in value
    with TestClient(app) as insecure:
        assert insecure.get("/api/auth/csrf").status_code == 503
    monkeypatch.delenv("AUTH_SIGNING_KEY")
    with TestClient(app, base_url="https://testserver") as secure:
        assert secure.get("/api/auth/csrf").status_code == 503
        assert secure.get("/api/health").status_code == 200


def test_expired_session_is_rejected_over_http(client, monkeypatch):
    import time

    monkeypatch.setenv("AUTH_SESSION_TTL_SECONDS", "1")
    assert sign_in(client).status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    time.sleep(1.1)
    assert client.get("/api/auth/me").status_code == 401


def test_inactive_user_loses_existing_session(client):
    engine = create_engine(
        os.environ["TEST_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
    )
    try:
        assert sign_in(client, login_id="participant-04").status_code == 200
        # Fixture models an operator disabling the account; assertions remain HTTP-only.
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE app_user SET active=false WHERE login_id='participant-04'")
            )
        assert client.get("/api/auth/me").status_code == 401
        assert sign_in(client, login_id="participant-04").status_code == 401
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE app_user SET active=true WHERE login_id='participant-04'")
            )
        engine.dispose()


def test_seed_cli_is_idempotent_and_never_rotates_existing_credentials(client, monkeypatch):
    first = sign_in(client).json()["user"]
    monkeypatch.setenv("DEMO_PARTICIPANT_PASSWORD", "different-secret-should-not-reset")
    result = subprocess.run(
        [sys.executable, "-m", "serentable.seed_demo_accounts"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "different-secret" not in result.stdout + result.stderr
    assert sign_in(client).json()["user"] == first
    monkeypatch.delenv("DEMO_PARTICIPANT_PASSWORD")
    result = subprocess.run(
        [sys.executable, "-m", "serentable.seed_demo_accounts"], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert result.stderr.strip() == "demo_password_environment_required"
    assert sign_in(client).json()["user"] == first


def test_auth_ui_routes_refresh_without_masking_unknown_paths():
    with TestClient(app) as browser:
        for route in (
            "/login",
            "/participant/profile",
            "/participant/consent",
            "/admin/participants",
        ):
            response = browser.get(route)
            assert response.status_code == 200
            assert '<div id="root"></div>' in response.text
        assert browser.get("/participant/not-implemented").status_code == 404
        assert browser.get("/admin/participants/not-implemented").status_code == 404
        assert browser.get("/api/unknown").status_code == 404


def test_cookie_session_and_login_limit_survive_real_api_restart(seeded_accounts):
    import contextlib
    import socket
    import time

    import httpx

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    environment = {**os.environ, "APP_ORIGIN": origin}

    @contextlib.contextmanager
    def api_process():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "serentable.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
                "--log-level",
                "error",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("isolated_api_process_exited")
                try:
                    if httpx.get(origin + "/api/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("isolated_api_process_not_ready")
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stderr.close()

    with httpx.Client(base_url=origin) as browser:
        with api_process():

            def headers():
                return {
                    "Origin": origin,
                    "X-CSRF-Token": browser.get("/api/auth/csrf").json()["csrf_token"],
                }

            response = browser.post(
                "/api/auth/login",
                headers=headers(),
                json={"login_id": "participant-03", "password": PARTICIPANT_PASSWORD},
            )
            assert response.status_code == 200
            user = response.json()
            for _ in range(5):
                failure = browser.post(
                    "/api/auth/login",
                    headers=headers(),
                    json={"login_id": "missing-throttle-account", "password": "invalid-password"},
                )
                assert failure.status_code == 401
            assert (
                browser.post(
                    "/api/auth/login",
                    headers=headers(),
                    json={"login_id": "missing-throttle-account", "password": "invalid-password"},
                ).status_code
                == 429
            )
        with api_process():
            assert browser.get("/api/auth/me").json() == user
            limited = browser.post(
                "/api/auth/login",
                headers=headers(),
                json={"login_id": "missing-throttle-account", "password": "invalid-password"},
            )
            assert limited.status_code == 429
            assert limited.headers["cache-control"] == "no-store"


def test_login_limit_reopens_after_five_minute_window(client):
    import hashlib
    from datetime import datetime, timedelta, timezone

    # Input fixture describes a previous window, not the expected output of the throttle code.
    engine = create_engine(
        os.environ["TEST_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
    )
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO auth_login_limit(login_key, failures, window_started)
            VALUES (:key, 5, :old)
        """),
            {
                "key": hashlib.sha256(b"participant-02").hexdigest(),
                "old": datetime.now(timezone.utc) - timedelta(minutes=6),
            },
        )
    engine.dispose()
    assert sign_in(client, login_id="participant-02").status_code == 200


def test_expired_csrf_signature_is_rejected(client, monkeypatch):
    import itsdangerous.timed

    with monkeypatch.context() as clock:
        clock.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp", lambda _: 1)
        stale = csrf_headers(client)
    response = client.post(
        "/api/auth/login",
        headers=stale,
        json={"login_id": "participant-01", "password": PARTICIPANT_PASSWORD},
    )
    assert response.status_code == 403
    assert sign_in(client).status_code == 200


def test_malformed_origin_setting_fails_safely(monkeypatch):
    monkeypatch.setenv("APP_ORIGIN", "https://[invalid-origin")
    monkeypatch.setenv("AUTH_SIGNING_KEY", KEY)
    with TestClient(app, raise_server_exceptions=False) as browser:
        response = browser.get("/api/auth/csrf")
    assert response.status_code == 503
    assert response.json() == {"detail": "auth_configuration_unavailable"}
