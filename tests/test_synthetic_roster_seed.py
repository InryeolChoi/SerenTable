"""Approved independent synthetic accounts through the CLI, then the app HTTP API."""

import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from support import login, send


def seed(*args, environment=None):
    return subprocess.run(
        [sys.executable, "-m", "serentable.seed_synthetic_roster", *args],
        env={**os.environ, "PYTHONPATH": "backend", **(environment or {})},
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def roster_database(monkeypatch):
    original = make_url(os.environ["TEST_DATABASE_URL"])
    name = "serentable_demo_test_" + uuid.uuid4().hex[:12]
    admin = create_engine(
        original.set(drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = original.set(database=name).render_as_string(hide_password=False)
    environment = {
        "DATABASE_URL": url,
        "SYNTHETIC_DEMO_SEED_ENABLED": "1",
        "DEMO_PARTICIPANT_PASSWORD": "synthetic-participant-password",
        "DEMO_OPERATOR_PASSWORD": "synthetic-operator-password",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("AUTH_SIGNING_KEY", "local-integration-test-signing-key-1234567890")
    try:
        for module, arguments in (
            ("alembic", ["upgrade", "head"]),
            ("serentable.seed_demo_accounts", []),
        ):
            subprocess.run(
                [sys.executable, "-m", module, *arguments],
                env={**os.environ, "PYTHONPATH": "backend"},
                check=True,
                capture_output=True,
            )
        yield environment
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_preview_describes_100_independent_profiles_without_database_or_password():
    result = seed("preview", environment={"DATABASE_URL": "", "DEMO_PARTICIPANT_PASSWORD": ""})
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["participant_count"] == 100
    assert report["source_linked"] is False
    assert report["login_prefix"] == "synthetic-demo-"
    assert report["birth_year_range"] == [1990, 2005]
    assert report["creates_consents"] is False
    assert report["creates_payments"] is False


def test_loaded_profiles_are_complete_and_replays_preserve_participant_edits(roster_database):
    first = seed("load")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["created_accounts"] == 100
    assert json.loads(first.stdout)["created_profiles"] == 100
    assert "synthetic-participant-password" not in first.stdout + first.stderr
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        roster = operator.get("/api/admin/participants").json()["participants"]
        synthetic = [row for row in roster if row["login_id"].startswith("synthetic-demo-")]
        assert len(synthetic) == 100
        assert all(row["profile_complete"] for row in synthetic)
        assert all(row["display_name"].startswith("합성 참가자 ") for row in synthetic)
        login(participant, "synthetic-demo-001")
        profile = participant.get("/api/me/profile").json()
        assert profile["complete"] is True
        assert profile["profile"]["contact"].startswith("DEMO-NOT-A-PHONE-")
        assert participant.get("/api/me/consents").json() == {"consents": [], "complete": False}
        assert participant.get("/api/me/applications").json()["applications"] == []
        assert participant.get("/api/me/entitlements").json()["entitlements"] == []
        changed = {**profile["profile"], "display_name": "수정한 합성 표시명"}
        assert send(participant, "PUT", "/api/me/profile", changed).status_code == 200
        replay = seed("load")
        assert replay.returncode == 0, replay.stderr
        assert json.loads(replay.stdout)["created_accounts"] == 0
        assert json.loads(replay.stdout)["created_profiles"] == 0
        assert participant.get("/api/me/profile").json()["profile"] == changed


def test_two_seed_processes_do_not_create_duplicate_rosters(roster_database):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: seed("load"), range(2)))
    assert [result.returncode for result in results] == [0, 0]
    assert sorted(json.loads(result.stdout)["created_accounts"] for result in results) == [0, 100]
    with TestClient(app) as operator:
        login(operator, "operator")
        rows = operator.get("/api/admin/participants").json()["participants"]
        assert sum(row["login_id"].startswith("synthetic-demo-") for row in rows) == 100


def test_a_mid_seed_database_failure_rolls_back_the_whole_roster(roster_database):
    engine = create_engine(
        make_url(roster_database["DATABASE_URL"]).set(drivername="postgresql+psycopg")
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""CREATE FUNCTION test_fail_roster() RETURNS trigger LANGUAGE plpgsql
                AS $$ BEGIN
                    IF NEW.data ->> 'display_name' = '합성 참가자 050' THEN
                        RAISE EXCEPTION 'PRIVATE-FAULT-SENTINEL';
                    END IF; RETURN NEW;
                END $$""")
            )
            connection.execute(
                text("""CREATE TRIGGER test_fail_roster BEFORE INSERT ON participant_profile
                FOR EACH ROW EXECUTE FUNCTION test_fail_roster()""")
            )
        try:
            result = seed("load")
            assert result.returncode == 1
            assert result.stderr.strip() == "synthetic_roster_unavailable"
            assert "PRIVATE-FAULT-SENTINEL" not in result.stdout + result.stderr
            with TestClient(app) as operator:
                login(operator, "operator")
                rows = operator.get("/api/admin/participants").json()["participants"]
                assert [row["login_id"] for row in rows] == [
                    "participant-01",
                    "participant-02",
                    "participant-03",
                    "participant-04",
                ]
        finally:
            with engine.begin() as connection:
                connection.execute(text("DROP TRIGGER test_fail_roster ON participant_profile"))
                connection.execute(text("DROP FUNCTION test_fail_roster()"))
        retried = seed("load")
        assert retried.returncode == 0, retried.stderr
        assert json.loads(retried.stdout)["created_accounts"] == 100
    finally:
        engine.dispose()


def test_an_existing_reserved_login_is_not_adopted_or_overwritten(roster_database):
    engine = create_engine(
        make_url(roster_database["DATABASE_URL"]).set(drivername="postgresql+psycopg")
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO app_user(id, login_id, password_hash, role, active)
                SELECT :id, 'synthetic-demo-050', password_hash, 'participant', true
                FROM app_user WHERE login_id = 'participant-01'"""),
                {"id": uuid.uuid4()},
            )
        failed = seed("load")
        assert failed.returncode == 1
        assert failed.stderr.strip() == "synthetic_roster_identity_conflict"
        with TestClient(app) as operator, TestClient(app) as participant:
            login(operator, "operator")
            rows = operator.get("/api/admin/participants").json()["participants"]
            assert sum(row["login_id"].startswith("synthetic-demo-") for row in rows) == 1
            login(participant, "synthetic-demo-050")
            assert participant.get("/api/me/profile").json()["profile"] is None
    finally:
        engine.dispose()


RAILWAY_ENVIRONMENT = {
    "APP_ENV": "production",
    "SYNTHETIC_DEMO_SEED_ENABLED": "1",
    "DEMO_PARTICIPANT_PASSWORD": "synthetic-participant-password",
    "DATABASE_URL": "postgresql://postgres:not-a-real-password@postgres.railway.internal/railway",
    "RAILWAY_PROJECT_ID": "e10b5d09-4b75-43c4-b46b-13414b96f11f",
    "RAILWAY_ENVIRONMENT_ID": "ec632dcd-2bc7-450c-9a98-bfc291c25338",
    "RAILWAY_SERVICE_ID": "b546da36-d001-49d7-943b-566f85420161",
}


def test_explicit_railway_preflight_accepts_only_the_known_app_target_without_connecting():
    result = seed("preflight", "--target", "railway", environment=RAILWAY_ENVIRONMENT)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["target"] == "railway" and report["configuration_valid"] is True
    assert "not-a-real-password" not in result.stdout + result.stderr
    assert "postgres.railway.internal" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "changes",
    [
        {"RAILWAY_PROJECT_ID": "another-project"},
        {"RAILWAY_ENVIRONMENT_ID": "another-environment"},
        {"RAILWAY_SERVICE_ID": "00478bf1-c6eb-4c37-8cea-eb3670a20143"},
        {"DATABASE_URL": "postgresql://example.invalid/railway"},
        {"DATABASE_URL": "postgresql://postgres.railway.internal/serentable_source_preparation"},
        {"DATABASE_URL": "postgresql://postgres.railway.internal/railway?host=example.invalid"},
        {"SYNTHETIC_DEMO_SEED_ENABLED": ""},
        {"PGHOSTADDR": "192.0.2.1"},
    ],
)
def test_railway_seed_refuses_other_targets_and_overrides_before_connecting(changes):
    result = seed("load", "--target", "railway", environment={**RAILWAY_ENVIRONMENT, **changes})
    assert result.returncode == 2
    assert result.stderr.strip() == "synthetic_roster_configuration_invalid"


def test_railway_environment_never_enables_a_remote_seed_implicitly():
    result = seed("load", environment=RAILWAY_ENVIRONMENT)
    assert result.returncode == 2
    assert result.stderr.strip() == "synthetic_roster_configuration_invalid"


@pytest.mark.parametrize(
    "changes",
    [
        {"SYNTHETIC_DEMO_SEED_ENABLED": ""},
        {"DEMO_PARTICIPANT_PASSWORD": "short"},
        {"APP_ENV": "production"},
        {"DATABASE_URL": "postgresql://example.invalid/serentable_demo_test"},
        {"DATABASE_URL": "postgresql://localhost/serentable_source_preparation"},
        {"DATABASE_URL": "postgresql://localhost/serentable_demo_test?host=example.invalid"},
        {"PGHOST": "example.invalid"},
    ],
)
def test_unsafe_seed_targets_are_refused_before_connecting(changes):
    result = seed(
        "load",
        environment={
            "SYNTHETIC_DEMO_SEED_ENABLED": "1",
            "DEMO_PARTICIPANT_PASSWORD": "synthetic-participant-password",
            "APP_ENV": "test",
            "DATABASE_URL": "postgresql://localhost/serentable_demo_test",
            **changes,
        },
    )
    assert result.returncode == 2
    assert "synthetic_roster_configuration_invalid" in result.stderr
