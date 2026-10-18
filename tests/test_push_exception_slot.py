"""Push exceptions keep their known event slot across listing and resolution."""

from contextlib import ExitStack
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.gatherings import run_gathering_jobs
from serentable.main import app
from serentable.notifications import dispatch_notifications, enqueue_notification
from sqlalchemy import text
from support import login, send, truncate
from test_admin_dashboard import confirmed_table, subscribe
from test_notifications import Provider, configure


def test_failed_table_push_keeps_slot_but_unrelated_notification_stays_unattributed(
    seeded_database, monkeypatch
):
    truncate("event_slot, participant_profile, consent_record, gathering_exception")
    configure(monkeypatch)
    provider = Provider(503)
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        slot = confirmed_table(operator, members)
        subscribe(members[0])
        run_gathering_jobs()
        owner = members[0].get("/api/auth/me").json()["user"]["id"]
        with database_engine().begin() as connection:
            enqueue_notification(
                connection,
                owner,
                "delivery:unrelated",
                "TEST",
                "private-notification-title",
                "private-notification-body",
                "/participant",
                datetime.now(timezone.utc),
            )
        for _ in range(3):
            assert dispatch_notifications(session=provider) == 3
            with database_engine().begin() as connection:
                connection.execute(text("UPDATE push_delivery SET next_attempt_at=now()"))

        path = "/api/admin/exceptions"
        assert members[0].get(path).status_code == 403
        listed = operator.get(path, params={"state": "OPEN"})
        assert listed.status_code == 200
        items = [e for e in listed.json()["exceptions"] if e["category"] == "PUSH_DELIVERY"]
        assert len(items) == 3
        attributed = [item for item in items if item["event_slot_id"] == slot]
        assert len(attributed) == 2
        assert len([item for item in items if item["event_slot_id"] is None]) == 1
        selected = attributed[0]
        resolve = f"{path}/gathering/{selected['id']}/resolve"
        assert send(members[0], "POST", resolve, {"note": "확인 완료"}).status_code == 403
        first = send(operator, "POST", resolve, {"note": "확인 완료"})
        assert first.status_code == 200, first.text
        assert first.json()["exception"]["event_slot_id"] == slot
        assert send(operator, "POST", resolve, {"note": "확인 완료"}).json() == first.json()
        resolved = operator.get(path, params={"state": "RESOLVED"})
        assert resolved.json()["exceptions"] == [first.json()["exception"]]
        audit = operator.get(
            "/api/admin/audit",
            params={"target_type": "gathering_exception", "target_id": selected["id"]},
        )
        assert audit.status_code == 200
        assert len(audit.json()["audit"]) == 1
        assert audit.json()["audit"][0]["action"] == "exception_resolve"
        for response in (listed, first, resolved, audit):
            for secret in (
                "private-notification-title",
                "private-notification-body",
                "provider-secret",
            ):
                assert secret not in response.text
