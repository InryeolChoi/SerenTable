"""Approved mock refund failure/retry contract at HTTP + isolated PostgreSQL."""

import uuid
from contextlib import contextmanager

from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login, send
from test_matching_resolution import choose, failure
from test_matching_runner import matching_database, prepare  # noqa: F401


@contextmanager
def refund_storage_fault():
    with database_engine().begin() as connection:
        connection.execute(
            text("""CREATE FUNCTION mock_refund_fault() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN IF NEW.state='REFUNDED' THEN
        RAISE EXCEPTION 'synthetic private failure'; END IF; RETURN NEW; END $$""")
        )
        connection.execute(
            text("""CREATE TRIGGER mock_refund_fault BEFORE UPDATE ON payment
        FOR EACH ROW EXECUTE FUNCTION mock_refund_fault()""")
        )
    try:
        yield
    finally:
        with database_engine().begin() as connection:
            connection.execute(text("DROP TRIGGER mock_refund_fault ON payment"))
            connection.execute(text("DROP FUNCTION mock_refund_fault()"))


def test_failed_mock_refund_is_visible_and_operator_retry_completes_once():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        run = owner.get(f"/api/me/applications/{application}/alternatives").json()["failure_run_id"]
        key = str(uuid.uuid4())
        with refund_storage_fault():
            response = choose(owner, application, "REFUND", key=key, run_id=run)
        assert response.status_code == 200, response.text
        resolution = response.json()["resolution"]
        assert resolution["refund_status"] == "FAILED"
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert mine["payments"][0]["state"] == "PAID"
        assert mine["matching_eligible_slot_ids"] == []
        assert mine["resolutions"][0]["refund_events"] == []
        assert (
            mine["resolutions"][0]["refund_attempts"][0]["error_code"]
            == "mock_refund_storage_failed"
        )
        items = operator.get("/api/admin/mock-refunds").json()["refunds"]
        assert len(items) == 1 and items[0]["amount_krw"] == 9900
        assert "synthetic private failure" not in str(items)
        path = f"/api/admin/mock-refunds/{resolution['id']}/retry"
        retry_key = str(uuid.uuid4())
        retried = send(operator, "POST", path, {"request_key": retry_key})
        assert retried.status_code == 200, retried.text
        assert retried.json()["refund"]["state"] == "SUCCEEDED"
        assert send(operator, "POST", path, {"request_key": retry_key}).json() == retried.json()
        assert (
            choose(owner, application, "REFUND", key=key, run_id=run).json()["resolution"][
                "refund_status"
            ]
            == "SUCCEEDED"
        )
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert mine["payments"][0]["state"] == "REFUNDED"
        assert len(mine["resolutions"][0]["refund_events"]) == 3
        assert len(mine["resolutions"][0]["refund_attempts"]) == 2
        assert operator.get("/api/admin/mock-refunds").json()["refunds"] == []
        audits = operator.get(
            "/api/admin/audit",
            params={"target_type": "match_resolution", "target_id": resolution["id"]},
        ).json()["audit"]
        assert len(audits) == 1


def test_retry_failure_and_concurrent_requests_never_double_refund_or_reopen_choices():
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        run = owner.get(f"/api/me/applications/{application}/alternatives").json()["failure_run_id"]
        with refund_storage_fault():
            initial = choose(owner, application, "REFUND", run_id=run).json()["resolution"]
            path = f"/api/admin/mock-refunds/{initial['id']}/retry"
            failed_key = str(uuid.uuid4())
            failed = send(operator, "POST", path, {"request_key": failed_key})
            assert failed.status_code == 200 and failed.json()["refund"]["state"] == "FAILED"
            assert send(operator, "POST", path, {"request_key": failed_key}).json() == failed.json()
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert mine["payments"][0]["state"] == "PAID"
        assert mine["matching_eligible_slot_ids"] == []
        assert len(mine["resolutions"][0]["refund_attempts"]) == 2
        assert choose(owner, application, "HOLD", run_id=run).status_code == 409
        assert choose(owner, application, "REFUND", run_id=run).status_code == 409
        right = owner.get("/api/me/entitlements").json()["entitlements"][0]
        assert right["reusable"] is False and right["reserved_application_id"] == application
        key = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [
                pool.submit(send, operator, "POST", path, {"request_key": key}) for _ in range(2)
            ]
            results = [job.result(timeout=15) for job in jobs]
        assert [result.status_code for result in results] == [200, 200]
        assert results[0].json() == results[1].json()
        assert results[0].json()["refund"]["attempt_number"] == 3
        assert send(operator, "POST", path, {"request_key": str(uuid.uuid4())}).status_code == 409
        # Replaying an old failed attempt is historical evidence, not another execution.
        assert send(operator, "POST", path, {"request_key": failed_key}).json() == failed.json()
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert len(mine["resolutions"][0]["refund_attempts"]) == 3
        assert len(mine["resolutions"][0]["refund_events"]) == 3
        assert mine["payments"][0]["state"] == "REFUNDED"
        assert owner.get("/api/me/entitlements").json()["entitlements"][0]["state"] == "REFUNDED"


def test_mock_refund_retry_has_operator_and_csrf_boundaries_and_rejects_amount():
    with TestClient(app) as operator, TestClient(app) as owner, TestClient(app) as anonymous:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        with refund_storage_fault():
            resolution = choose(owner, application, "REFUND").json()["resolution"]
        path = f"/api/admin/mock-refunds/{resolution['id']}/retry"
        payload = {"request_key": str(uuid.uuid4())}
        assert owner.get("/api/admin/mock-refunds").status_code == 403
        assert anonymous.get("/api/admin/mock-refunds").status_code == 401
        assert send(owner, "POST", path, payload).status_code == 403
        assert send(anonymous, "POST", path, payload).status_code == 401
        assert operator.post(path, json=payload).status_code == 403
        assert send(operator, "POST", path, payload | {"amount_krw": 1}).status_code == 422
        assert (
            send(
                operator, "POST", f"/api/admin/mock-refunds/{uuid.uuid4()}/retry", payload
            ).status_code
            == 404
        )
        assert operator.get("/api/admin/mock-refunds").json()["refunds"][0]["state"] == "FAILED"


def test_operator_retry_audit_failure_rolls_back_refund_and_same_request_can_retry():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        with refund_storage_fault():
            resolution = choose(owner, application, "REFUND").json()["resolution"]
        path = f"/api/admin/mock-refunds/{resolution['id']}/retry"
        key = str(uuid.uuid4())
        before = owner.get("/api/me/applications").json()
        with database_engine().begin() as connection:
            connection.execute(
                text("""CREATE FUNCTION refund_audit_fault() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private audit failure'; END $$""")
            )
            connection.execute(
                text("""CREATE TRIGGER refund_audit_fault BEFORE INSERT ON operator_audit
            FOR EACH ROW EXECUTE FUNCTION refund_audit_fault()""")
            )
        try:
            response = send(operator, "POST", path, {"request_key": key})
            assert response.status_code == 503
            assert "private audit failure" not in response.text
            assert owner.get("/api/me/applications").json() == before
        finally:
            with database_engine().begin() as connection:
                connection.execute(text("DROP TRIGGER refund_audit_fault ON operator_audit"))
                connection.execute(text("DROP FUNCTION refund_audit_fault()"))
        assert (
            send(operator, "POST", path, {"request_key": key}).json()["refund"]["state"]
            == "SUCCEEDED"
        )


def test_failure_record_storage_failure_rolls_back_initial_choice_without_losing_right():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        run = owner.get(f"/api/me/applications/{application}/alternatives").json()["failure_run_id"]
        before = owner.get("/api/me/applications").json()
        with database_engine().begin() as connection:
            connection.execute(
                text("""CREATE FUNCTION refund_attempt_fault() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private record failure'; END $$""")
            )
            connection.execute(
                text("""CREATE TRIGGER refund_attempt_fault BEFORE INSERT ON mock_refund_attempt
            FOR EACH ROW EXECUTE FUNCTION refund_attempt_fault()""")
            )
        key = str(uuid.uuid4())
        try:
            with refund_storage_fault():
                response = choose(owner, application, "REFUND", key=key, run_id=run)
            assert response.status_code == 503
            assert owner.get("/api/me/applications").json() == before
        finally:
            with database_engine().begin() as connection:
                connection.execute(text("DROP TRIGGER refund_attempt_fault ON mock_refund_attempt"))
                connection.execute(text("DROP FUNCTION refund_attempt_fault()"))
        assert (
            choose(owner, application, "REFUND", key=key, run_id=run).json()["resolution"][
                "refund_status"
            ]
            == "SUCCEEDED"
        )


def test_retry_key_cannot_target_a_different_failed_refund():
    with TestClient(app) as operator, TestClient(app) as first, TestClient(app) as second:
        login(operator, "operator")
        prepare(first, "participant-01")
        prepare(second, "participant-02")
        one = failure(first, operator)
        import time

        from serentable.matching import run_slot_matching
        from test_matching_runner import apply_and_pay, due_slot

        slot = due_slot(operator, region="gangnam", close_in=1.0)
        two = apply_and_pay(second, slot)
        time.sleep(1.6)
        assert run_slot_matching(slot)["seated_count"] == 0
        with refund_storage_fault():
            first_resolution = choose(first, one, "REFUND").json()["resolution"]["id"]
            second_resolution = choose(second, two, "REFUND").json()["resolution"]["id"]
        key = str(uuid.uuid4())
        path = f"/api/admin/mock-refunds/{first_resolution}/retry"
        assert send(operator, "POST", path, {"request_key": key}).status_code == 200
        other = f"/api/admin/mock-refunds/{second_resolution}/retry"
        assert send(operator, "POST", other, {"request_key": key}).status_code == 409
        mine = second.get("/api/me/applications").json()["applications"][0]
        assert mine["payments"][0]["state"] == "PAID"
        assert mine["resolutions"][0]["refund_status"] == "FAILED"


def test_additive_migration_keeps_legacy_successful_refund_without_fabricating_attempts():
    import subprocess
    import sys

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        resolution = choose(owner, application, "REFUND").json()["resolution"]["id"]
        # In this isolated fixture, removing only the new attempt table recreates the
        # existing 0013 successful refund shape, retaining original events and payment.
        subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0013_operator_audit"], check=True
        )
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert mine["payments"][0]["state"] == "REFUNDED"
        assert mine["resolutions"][0]["refund_status"] == "SUCCEEDED"
        assert mine["resolutions"][0]["refund_attempts"] == []
        assert len(mine["resolutions"][0]["refund_events"]) == 3
        assert operator.get("/api/admin/mock-refunds").json()["refunds"] == []
        assert (
            send(
                operator,
                "POST",
                f"/api/admin/mock-refunds/{resolution}/retry",
                {"request_key": str(uuid.uuid4())},
            ).status_code
            == 409
        )


def test_deferred_commit_failure_does_not_report_or_persist_a_refund():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        run = owner.get(f"/api/me/applications/{application}/alternatives").json()["failure_run_id"]
        before = owner.get("/api/me/applications").json()
        rights = owner.get("/api/me/entitlements").json()
        with database_engine().begin() as connection:
            connection.execute(
                text("""CREATE FUNCTION refund_commit_fault() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private deferred failure'; END $$""")
            )
            connection.execute(
                text("""CREATE CONSTRAINT TRIGGER refund_commit_fault
            AFTER INSERT ON mock_refund_attempt DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION refund_commit_fault()""")
            )
        key = str(uuid.uuid4())
        try:
            response = choose(owner, application, "REFUND", key=key, run_id=run)
            assert response.status_code == 503
            assert "private deferred failure" not in response.text
            assert owner.get("/api/me/applications").json() == before
            assert owner.get("/api/me/entitlements").json() == rights
            assert operator.get("/api/admin/mock-refunds").json()["refunds"] == []
        finally:
            with database_engine().begin() as connection:
                connection.execute(text("DROP TRIGGER refund_commit_fault ON mock_refund_attempt"))
                connection.execute(text("DROP FUNCTION refund_commit_fault()"))
        assert (
            choose(owner, application, "REFUND", key=key, run_id=run).json()["resolution"][
                "refund_status"
            ]
            == "SUCCEEDED"
        )


def test_different_retry_keys_and_separate_worker_only_refund_once():
    import subprocess
    import sys
    import threading
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        with refund_storage_fault():
            resolution = choose(owner, application, "REFUND").json()["resolution"]
        path = f"/api/admin/mock-refunds/{resolution['id']}/retry"
        ready = threading.Barrier(3)

        def retry(key):
            ready.wait(timeout=10)
            return send(operator, "POST", path, {"request_key": key})

        def worker():
            ready.wait(timeout=10)
            return subprocess.run(
                [sys.executable, "-m", "serentable.worker", "--once"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            attempts = [pool.submit(retry, str(uuid.uuid4())) for _ in range(2)]
            background = pool.submit(worker)
            results = [attempt.result(timeout=30) for attempt in attempts]
            worker_result = background.result(timeout=35)
            assert worker_result.returncode == 0
            assert "worker_heartbeat_ok" in worker_result.stderr
            assert "unavailable" not in worker_result.stderr
        assert sorted(result.status_code for result in results) == [200, 409]
        successful = next(result for result in results if result.status_code == 200)
        assert successful.json()["refund"]["state"] == "SUCCEEDED"
        assert successful.json()["refund"]["attempt_number"] == 2
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert mine["payments"][0]["state"] == "REFUNDED"
        assert mine["matching"]["state"] == "NO_MATCH"
        assert mine["matching_eligible_slot_ids"] == []
        assert len(mine["resolutions"][0]["refund_attempts"]) == 2
        assert [event["state"] for event in mine["resolutions"][0]["refund_events"]] == [
            "REFUND_REQUESTED",
            "REFUND_PROCESSING",
            "REFUNDED",
        ]
        audits = operator.get(
            "/api/admin/audit",
            params={"target_type": "match_resolution", "target_id": resolution["id"]},
        ).json()["audit"]
        assert len(audits) == 1
        assert operator.get("/api/admin/mock-refunds").json()["refunds"] == []
