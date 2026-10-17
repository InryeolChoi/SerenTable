"""Kill the actual worker before commit; observe recovery through the public API.

The advisory lock and trigger are disposable PostgreSQL fault fixtures. Business results
are checked over HTTP, not by reading the runner's private tables as expected values.
"""

import os
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack

from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login
from test_matching_runner import (  # noqa: F401
    apply_and_pay,
    due_slot,
    matching_database,
    prepare,
)


def test_killed_worker_rolls_back_confirmation_and_a_new_process_recovers_once():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, 1):
            prepare(participant, f"participant-0{index}")
        slot = due_slot(operator)
        for participant in members:
            apply_and_pay(participant, slot)
        time.sleep(3.6)

        # Stop at the final confirmation write, after table assignments were made but
        # before commit. A unique PG application name identifies only our child process.
        marker = f"crash-test-{uuid.uuid4()}"
        lock_key = 710171035
        worker = None
        blocker = database_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            blocker.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
            with database_engine().begin() as connection:
                connection.execute(
                    text(f"""CREATE FUNCTION test_block_confirmation() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN
                        IF NEW.state = 'SUCCEEDED' THEN
                            PERFORM pg_advisory_xact_lock({lock_key});
                        END IF; RETURN NEW;
                    END $$""")
                )
                connection.execute(
                    text("""CREATE TRIGGER test_block_confirmation
                    BEFORE UPDATE ON match_run FOR EACH ROW
                    EXECUTE FUNCTION test_block_confirmation()""")
                )
            worker = subprocess.Popen(
                [sys.executable, "-m", "serentable.worker", "--once"],
                env={**os.environ, "PYTHONPATH": "backend", "PGAPPNAME": marker},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                with database_engine().connect() as observer:
                    waiting = observer.execute(
                        text("""SELECT EXISTS (SELECT 1 FROM pg_stat_activity
                        WHERE application_name = :marker AND wait_event_type = 'Lock'
                          AND wait_event = 'advisory')"""),
                        {"marker": marker},
                    ).scalar()
                if waiting:
                    break
                assert worker.poll() is None, "worker exited before the crash fixture"
                time.sleep(0.05)
            else:
                raise AssertionError("worker did not reach the pre-commit crash fixture")

            # Uncommitted assignments and entitlement use must never be published.
            assert operator.get("/api/admin/match-runs").json()["match_runs"] == []
            for participant in members:
                (held,) = participant.get("/api/me/entitlements").json()["entitlements"]
                assert held["state"] == "HELD" and held["used_at"] is None

            worker.kill()  # Actual abrupt process death, without Python cleanup handlers.
            worker.communicate(timeout=10)
            assert worker.returncode < 0
        finally:
            if worker is not None:
                if worker.poll() is None:
                    worker.kill()
                worker.communicate(timeout=10)
            blocker.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
            blocker.close()
            # A blocked server backend may finish unwinding only after releasing the
            # fixture lock. DDL waits for that transaction; bound that wait explicitly.
            with database_engine().begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                connection.execute(
                    text("DROP TRIGGER IF EXISTS test_block_confirmation ON match_run")
                )
                connection.execute(text("DROP FUNCTION IF EXISTS test_block_confirmation()"))

        assert operator.get("/api/admin/match-runs").json()["match_runs"] == []
        for participant in members:
            (application,) = participant.get("/api/me/applications").json()["applications"]
            assert application["matching"] is None
            (held,) = participant.get("/api/me/entitlements").json()["entitlements"]
            assert held["state"] == "HELD" and held["used_at"] is None

        def restart():
            result = subprocess.run(
                [sys.executable, "-m", "serentable.worker", "--once"],
                env={**os.environ, "PYTHONPATH": "backend"},
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            assert "worker_heartbeat_ok" in result.stderr
            assert "worker_matching_unavailable" not in result.stderr
            assert "worker_database_unavailable" not in result.stderr
            return result

        assert "worker_matching_ok runs=1" in restart().stderr
        (run,) = operator.get("/api/admin/match-runs").json()["match_runs"]
        assert (run["state"], run["attempt"], run["seated_count"]) == ("SUCCEEDED", 1, 4)
        assert len(run["members"]) == 4
        assert {member["outcome"] for member in run["members"]} == {"SEATED"}
        assert len({member["dining_table_id"] for member in run["members"]}) == 1
        used = []
        for participant in members:
            (application,) = participant.get("/api/me/applications").json()["applications"]
            assert application["matching"]["state"] == "CONFIRMED"
            assert application["matching"]["table"]["member_count"] == 4
            (entitlement,) = participant.get("/api/me/entitlements").json()["entitlements"]
            assert entitlement["state"] == "USED" and entitlement["used_at"] is not None
            used.append(entitlement)
        assert "worker_matching_ok" not in restart().stderr
        assert operator.get("/api/admin/match-runs").json()["match_runs"] == [run]
        for participant, expected in zip(members, used, strict=True):
            assert participant.get("/api/me/entitlements").json()["entitlements"] == [expected]
