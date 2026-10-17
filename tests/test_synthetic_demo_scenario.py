"""The demo scenario runs through a real HTTP server, PostgreSQL and a separate worker."""

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from oracle.hard_constraints import Participant, Table, validate_assignment
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_applications import COMPLETE_PROFILE
from test_synthetic_roster_seed import roster_database, seed  # noqa: F401


@pytest.fixture
def scenario_server(request):
    database_environment = request.getfixturevalue("roster_database")
    assert seed("load").returncode == 0
    with socket.socket() as socket_:
        socket_.bind(("127.0.0.1", 0))
        port = socket_.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    environment = {**database_environment, "PYTHONPATH": "backend", "APP_ORIGIN": origin}
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "serentable.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env={**os.environ, **environment},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if httpx.get(origin + "/api/readiness", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert server.poll() is None, "scenario HTTP server exited before readiness"
            time.sleep(0.05)
        else:
            raise AssertionError("scenario HTTP server did not become ready")
        yield origin, environment
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


def request(client, method, path, payload=None):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.request(method, path, json=payload, headers={"X-CSRF-Token": token})


def authenticate(client, account):
    role = "operator" if account == "operator" else "participant"
    response = request(
        client,
        "POST",
        "/api/auth/login",
        {
            "login_id": account,
            "password": f"synthetic-{role}-password",
        },
    )
    assert response.status_code == 200, response.status_code


def scenario(slot, environment):
    return subprocess.run(
        [sys.executable, "-m", "serentable.seed_demo_scenario", "--slot-id", slot],
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        timeout=90,
    )


def test_100_synthetic_applications_and_mock_payments_replay_and_match_once(scenario_server):
    origin, environment = scenario_server
    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as operator:
        authenticate(operator, "operator")
        now = datetime.now().astimezone()
        close = now + timedelta(seconds=90)
        created = request(
            operator,
            "POST",
            "/api/admin/event-slots",
            {
                "region_code": "hongdae",
                "starts_at": (now + timedelta(days=7)).isoformat(),
                "ends_at": (now + timedelta(days=7, hours=2)).isoformat(),
                "closes_at": close.isoformat(),
                "matches_at": (close + timedelta(seconds=0.5)).isoformat(),
                "capacity": 100,
            },
        )
        assert created.status_code == 201
        slot = created.json()["event_slot"]["id"]
        first = scenario(slot, environment)
        assert first.returncode == 0, first.stderr
        assert json.loads(first.stdout)["ready_participants"] == 100
        assert "synthetic-participant-password" not in first.stdout + first.stderr
        applications = operator.get("/api/admin/applications").json()["applications"]
        assert len(applications) == 100
        assert len({row["id"] for row in applications}) == 100
        assert all(len(row["payments"]) == 1 and row["payments"][0]["mock"] for row in applications)
        before = {row["id"]: row["payments"] for row in applications}
        replay = scenario(slot, environment)
        assert replay.returncode == 0, replay.stderr
        applications = operator.get("/api/admin/applications").json()["applications"]
        assert {row["id"]: row["payments"] for row in applications} == before
        time.sleep(
            max(0, (close + timedelta(seconds=0.7) - datetime.now().astimezone()).total_seconds())
        )
        worker = subprocess.run(
            [sys.executable, "-m", "serentable.worker", "--once"],
            env={**os.environ, **environment},
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        assert "worker_matching_ok runs=1" in worker.stderr
        (run,) = operator.get("/api/admin/match-runs").json()["match_runs"]
        assert (run["state"], run["seated_count"]) == ("SUCCEEDED", 100)
        roster = [
            Participant(
                id=row["id"],
                paid=True,
                consented_slots=frozenset({slot}),
                birth_year=1990 + (int(row["participant"]["login_id"].rsplit("-", 1)[1]) - 1) % 16,
            )
            for row in applications
        ]
        groups = {}
        for member in run["members"]:
            groups.setdefault(member["dining_table_id"], []).append(member["application_id"])
        assert (
            validate_assignment(
                roster, [Table(key, slot, tuple(ids)) for key, ids in groups.items()]
            )
            == []
        )
        after_close = scenario(slot, environment)
        assert after_close.returncode == 0, after_close.stderr
        assert operator.get("/api/admin/match-runs").json()["match_runs"] == [run]
        applications = operator.get("/api/admin/applications").json()["applications"]
        assert {row["id"]: row["payments"] for row in applications} == before
    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as untouched:
        authenticate(untouched, "participant-01")
        assert untouched.get("/api/me/profile").json()["profile"] is None
        assert untouched.get("/api/me/consents").json()["complete"] is False
        assert untouched.get("/api/me/applications").json()["applications"] == []


@pytest.mark.parametrize("condition", ["mixed_slot", "withdrawn_consent"])
def test_scenario_refuses_mixed_participants_and_prior_refusals_before_writing(
    scenario_server, condition
):
    origin, environment = scenario_server
    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as operator:
        authenticate(operator, "operator")
        now = datetime.now().astimezone()
        created = request(
            operator,
            "POST",
            "/api/admin/event-slots",
            {
                "region_code": "hongdae",
                "starts_at": (now + timedelta(days=7)).isoformat(),
                "ends_at": (now + timedelta(days=7, hours=2)).isoformat(),
                "closes_at": (now + timedelta(minutes=10)).isoformat(),
                "matches_at": (now + timedelta(minutes=11)).isoformat(),
                "capacity": 100,
            },
        )
        assert created.status_code == 201
        slot = created.json()["event_slot"]["id"]
        account = "participant-01" if condition == "mixed_slot" else "synthetic-demo-100"
        with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as changed:
            authenticate(changed, account)
            assert (
                request(
                    changed,
                    "PUT",
                    "/api/me/consents",
                    {
                        "consents": [
                            {
                                "purpose": p,
                                "version": "demo-2026-10-16",
                                "accepted": condition == "mixed_slot",
                            }
                            for p in ("privacy", "operation")
                        ]
                    },
                ).status_code
                == 200
            )
            if condition == "mixed_slot":
                assert (
                    request(changed, "PUT", "/api/me/profile", COMPLETE_PROFILE).status_code == 200
                )
                assert (
                    request(
                        changed,
                        "POST",
                        "/api/me/applications",
                        {
                            "request_key": "a51339b0-0761-4c03-af47-216ec4874f96",
                            "event_slot_ids": [slot],
                        },
                    ).status_code
                    == 201
                )
            before = changed.get("/api/me/consents").json()
            result = scenario(slot, environment)
            assert result.returncode == 1
            expected = (
                "scenario_mixed_slot_refused"
                if condition == "mixed_slot"
                else "scenario_existing_consent_change_refused"
            )
            assert expected in result.stderr and "completed=0" in result.stderr
            assert changed.get("/api/me/consents").json() == before
        applications = operator.get("/api/admin/applications").json()["applications"]
        assert len(applications) == (1 if condition == "mixed_slot" else 0)
    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as first:
        authenticate(first, "synthetic-demo-001")
        assert first.get("/api/me/consents").json() == {"consents": [], "complete": False}
        assert first.get("/api/me/applications").json()["applications"] == []


def test_a_partial_http_preparation_resumes_without_duplicate_mock_payments(scenario_server):
    origin, environment = scenario_server
    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as operator:
        authenticate(operator, "operator")
        now = datetime.now().astimezone()
        created = request(
            operator,
            "POST",
            "/api/admin/event-slots",
            {
                "region_code": "hongdae",
                "starts_at": (now + timedelta(days=7)).isoformat(),
                "ends_at": (now + timedelta(days=7, hours=2)).isoformat(),
                "closes_at": (now + timedelta(minutes=10)).isoformat(),
                "matches_at": (now + timedelta(minutes=11)).isoformat(),
                "capacity": 100,
            },
        )
        assert created.status_code == 201
        slot = created.json()["event_slot"]["id"]
        roster = operator.get("/api/admin/participants").json()["participants"]
        target = uuid.UUID(
            next(row["id"] for row in roster if row["login_id"] == "synthetic-demo-050")
        )
        engine = create_engine(
            make_url(environment["DATABASE_URL"]).set(drivername="postgresql+psycopg")
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(f"""CREATE FUNCTION test_fail_scenario() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN
                    IF NEW.user_id = '{target}'::uuid THEN
                        RAISE EXCEPTION 'PRIVATE-FAULT-SENTINEL';
                    END IF; RETURN NEW;
                END $$""")
                )
                connection.execute(
                    text("""CREATE TRIGGER test_fail_scenario BEFORE INSERT ON payment
                FOR EACH ROW EXECUTE FUNCTION test_fail_scenario()""")
                )
            try:
                failed = scenario(slot, environment)
                assert failed.returncode == 1
                assert "scenario_http_unavailable; completed=49" in failed.stderr
                assert "PRIVATE-FAULT-SENTINEL" not in failed.stdout + failed.stderr
                partial = operator.get("/api/admin/applications").json()["applications"]
                assert len(partial) == 50
                assert sum(bool(row["payments"]) for row in partial) == 49
                payments = {row["id"]: row["payments"] for row in partial if row["payments"]}
            finally:
                with engine.begin() as connection:
                    connection.execute(text("DROP TRIGGER test_fail_scenario ON payment"))
                    connection.execute(text("DROP FUNCTION test_fail_scenario()"))
            recovered = scenario(slot, environment)
            assert recovered.returncode == 0, recovered.stderr
            complete = operator.get("/api/admin/applications").json()["applications"]
            assert len(complete) == 100
            assert all(len(row["payments"]) == 1 for row in complete)
            assert {
                row["id"]: row["payments"] for row in complete if row["id"] in payments
            } == payments
        finally:
            engine.dispose()
