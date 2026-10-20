"""PRD §14 participant notices and §7.4 alternative order, at the HTTP / PostgreSQL boundary."""

import time
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from serentable.clock import SEOUL
from serentable.main import app
from serentable.matching import run_slot_matching
from support import login, send
from test_applications import apply
from test_matching_resolution import choose
from test_matching_runner import (  # noqa: F401
    due_slot,
    matching_database,
    prepare,
)
from test_payments import pay


def new_notices(client, seen):
    """Notices that appeared since `seen`, oldest first. Earlier tests may leave others."""
    rows = client.get("/api/me/notifications").json()["notifications"]
    return [row for row in reversed(rows) if row["id"] not in seen]


def ids(client):
    return {row["id"] for row in client.get("/api/me/notifications").json()["notifications"]}


def slot_at(operator, day, hour, region):
    """A recruiting slot `day` days ahead at `hour`:00 Seoul time."""
    starts = (datetime.now(SEOUL) + timedelta(days=day)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    closes = datetime.now(SEOUL) + timedelta(days=1)
    response = send(
        operator,
        "POST",
        "/api/admin/event-slots",
        {
            "region_code": region,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "closes_at": closes.isoformat(),
            "matches_at": (closes + timedelta(minutes=1)).isoformat(),
            "capacity": 24,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["event_slot"]["id"]


def failed_application(owner, operator):
    slot = due_slot(operator, close_in=1.0)
    application = apply(owner, [slot]).json()["application"]["id"]
    assert pay(owner, application, "single").status_code == 201
    time.sleep(1.6)
    assert run_slot_matching(slot)["seated_count"] == 0
    return application


def test_submission_payment_failure_and_hold_each_notify_once():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        seen = ids(owner)
        slot = due_slot(operator, close_in=1.0)
        key = str(uuid.uuid4())
        submitted = send(
            owner, "POST", "/api/me/applications", {"event_slot_ids": [slot], "request_key": key}
        )
        assert submitted.status_code == 201, submitted.text
        application = submitted.json()["application"]["id"]
        # A replayed submission returns the same application and no second notice.
        send(owner, "POST", "/api/me/applications", {"event_slot_ids": [slot], "request_key": key})
        assert pay(owner, application, "single").status_code == 201
        time.sleep(1.6)
        assert run_slot_matching(slot)["seated_count"] == 0
        assert choose(owner, application, "HOLD").status_code == 200
        notices = new_notices(owner, seen)
        assert [n["kind"] for n in notices] == [
            "APPLICATION_SUBMITTED",
            "PAYMENT_COMPLETED",
            "MATCHING_FAILED",
            "PASS_HELD",
        ]
        submitted_notice, paid, failed, held = notices
        assert "결제 대기" in submitted_notice["body"] and "신청 마감" in submitted_notice["body"]
        assert "1회권 9,900원" in paid["body"] and "자동 매칭은" in paid["body"]
        assert "사유:" in failed["body"]
        assert all(word in failed["body"] for word in ("이동", "이용권 보관", "환불"))
        assert "이용권을 보관" in held["body"]
        assert all(n["url"] == "/participant" and n["table_id"] is None for n in notices)


def test_refund_completion_is_notified_with_the_amount():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failed_application(owner, operator)
        seen = ids(owner)
        key = str(uuid.uuid4())
        run = owner.get(f"/api/me/applications/{application}/alternatives").json()
        refund = {"key": key, "run_id": run["failure_run_id"]}
        assert choose(owner, application, "REFUND", **refund).status_code == 200
        assert choose(owner, application, "REFUND", **refund).status_code == 200
        (notice,) = new_notices(owner, seen)
        assert notice["kind"] == "REFUND_COMPLETED"
        assert "9,900원" in notice["body"] and "실제 입출금은 없습니다" in notice["body"]


def test_alternatives_follow_prd_order_and_transfer_is_notified():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failed_application(owner, operator)
        # The failed slot is hongdae, seven days ahead at 19:00 (due_slot).
        later_same_region = slot_at(operator, 9, 19, "hongdae")
        later_other_region = slot_at(operator, 8, 19, "gangnam")
        same_day_other_region = slot_at(operator, 7, 20, "gangnam")
        same_day_same_region = slot_at(operator, 7, 12, "hongdae")
        offer = owner.get(f"/api/me/applications/{application}/alternatives").json()
        ours = {
            same_day_same_region,
            same_day_other_region,
            later_same_region,
            later_other_region,
        }
        listed = [(s["id"], s["preference"]) for s in offer["alternatives"] if s["id"] in ours]
        assert listed == [
            (same_day_same_region, "same_date_same_region"),
            (same_day_other_region, "same_date_other_region"),
            (later_same_region, "other_date_same_region"),
            (later_other_region, "other_date_other_region"),
        ]
        seen = ids(owner)
        moved = choose(owner, application, "TRANSFER", same_day_same_region)
        assert moved.status_code == 200, moved.text
        (notice,) = new_notices(owner, seen)
        assert notice["kind"] == "SCHEDULE_MOVED"
        assert "홍대" in notice["body"] and "자동 매칭은" in notice["body"]
