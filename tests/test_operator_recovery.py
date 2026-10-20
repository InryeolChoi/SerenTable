"""Approved operator exception list/count and participant rights at real HTTP + PG."""

from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login, send
from test_matching_resolution import choose, failure
from test_matching_runner import matching_database, prepare  # noqa: F401
from test_mock_refund_retry import refund_storage_fault


def test_failed_refund_list_and_dashboard_agree_then_retry_clears_exception():
    import uuid

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        with refund_storage_fault():
            resolution = choose(owner, application, "REFUND").json()["resolution"]
        response = operator.get("/api/admin/exceptions", params={"state": "OPEN"})
        (item,) = response.json()["exceptions"]
        assert item["kind"] == "mock_refund" and item["id"] == resolution["id"]
        assert item["retryable"] is True and item["amount_krw"] == 9900
        slot = item["event_slot_id"]
        summary = operator.get("/api/admin/dashboard", params={"event_slot_id": slot}).json()[
            "slots"
        ][0]
        assert summary["open_exception_count"] == 1
        assert summary["failed_refund_count"] == 1
        assert (
            send(
                operator,
                "POST",
                f"/api/admin/mock-refunds/{item['id']}/retry",
                {"request_key": str(uuid.uuid4())},
            ).status_code
            == 200
        )
        assert (
            operator.get("/api/admin/exceptions", params={"state": "OPEN"}).json()["exceptions"]
            == []
        )
        resolved = operator.get("/api/admin/exceptions", params={"state": "RESOLVED"}).json()[
            "exceptions"
        ]
        assert len(resolved) == 1 and resolved[0]["retryable"] is False
        summary = operator.get("/api/admin/dashboard", params={"event_slot_id": slot}).json()[
            "slots"
        ][0]
        assert summary["open_exception_count"] == 0


def test_overdue_display_does_not_expire_participant_hold_choice():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        before = owner.get(f"/api/me/applications/{application}/alternatives").json()
        assert operator.get("/api/admin/exceptions").json()["exceptions"] == []
        # Existing isolated clock fixture; no production clock override.
        with database_engine().begin() as connection:
            connection.execute(
                text("""UPDATE event_slot SET closes_at=now()-interval '3 minutes',
                matches_at=now()-interval '2 minutes', starts_at=now()-interval '1 minute',
                ends_at=now()+interval '1 hour' WHERE id=(SELECT event_slot_id FROM match_run
                    WHERE id=:run)"""),
                {"run": before["failure_run_id"]},
            )
        (item,) = operator.get("/api/admin/exceptions").json()["exceptions"]
        assert item["kind"] == "alternative_overdue" and item["resolvable"] is False
        summary = operator.get(
            "/api/admin/dashboard", params={"event_slot_id": item["event_slot_id"]}
        ).json()["slots"][0]
        assert summary["open_exception_count"] == 1
        assert owner.get(f"/api/me/applications/{application}/alternatives").status_code == 200
        assert (
            choose(owner, application, "HOLD", run_id=before["failure_run_id"]).status_code == 200
        )
        assert operator.get("/api/admin/exceptions").json()["exceptions"] == []
        assert owner.get("/api/me/entitlements").json()["entitlements"][0]["reusable"] is True
