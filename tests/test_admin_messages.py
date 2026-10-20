"""PRD §11·§17 table detail and automatic message views, at the HTTP / PostgreSQL boundary."""

import time
from contextlib import ExitStack

from fastapi.testclient import TestClient
from serentable.gatherings import run_gathering_jobs
from serentable.main import app
from serentable.matching import run_slot_matching
from support import login
from test_matching_runner import (  # noqa: F401
    apply_and_pay,
    due_slot,
    matching_database,
    prepare,
)


def test_operator_sees_table_detail_and_message_history_participants_do_not():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, member in enumerate(members, 1):
            prepare(member, f"participant-0{i}")
        slot = due_slot(operator, close_in=2.0)
        for member in members:
            apply_and_pay(member, slot)
        time.sleep(2.6)
        assert run_slot_matching(slot)["seated_count"] == 4
        run_gathering_jobs()

        (table,) = operator.get("/api/admin/table-details").json()["tables"]
        assert table["members"] == [f"participant-0{i}" for i in range(1, 5)]
        assert table["member_count"] == 4 and table["region_name"] == "홍대"
        # No inventory was registered, so the venue waits and the room still opens.
        assert table["venue"] is None and table["room_id"] and table["message_count"] >= 1
        # CONFIRMED and VENUE_PENDING per member; nobody subscribed to push here.
        assert table["notices"] == {"not_subscribed": 8}

        body = operator.get("/api/admin/messages").json()
        kinds = {t["kind"] for t in body["templates"]}
        assert {"APPLICATION_SUBMITTED", "MATCHING_FAILED", "CONFIRMED", "REMINDER"} <= kinds
        sent = {(h["login_id"], h["kind"]) for h in body["history"]}
        for i in range(1, 5):
            for kind in ("APPLICATION_SUBMITTED", "PAYMENT_COMPLETED", "CONFIRMED"):
                assert (f"participant-0{i}", kind) in sent
        assert all(h["push_status"] == "not_subscribed" for h in body["history"])

        for path in ("/api/admin/table-details", "/api/admin/messages"):
            assert members[0].get(path).status_code == 403
