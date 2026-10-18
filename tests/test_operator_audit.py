"""Work #9 C: operator writes leave one audit row each, readable only by operators."""

import json
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.gatherings import run_gathering_jobs
from serentable.main import app
from serentable.matching import run_due_matches
from sqlalchemy import text
from support import SEOUL, login, send, truncate
from test_attendance import move_slot
from test_matching_runner import apply_and_pay, due_slot, prepare

AUDIT = "/api/admin/audit"


@pytest.fixture(autouse=True)
def audit_database(seeded_database):
    truncate("operator_audit, event_slot, participant_profile, consent_record")
    yield
    truncate("operator_audit")


def slot_payload(days=7):
    start = (datetime.now(SEOUL) + timedelta(days=days)).replace(
        hour=19, minute=0, second=0, microsecond=0
    )
    closes = start - timedelta(days=2)
    return {
        "region_code": "hongdae",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=2)).isoformat(),
        "closes_at": closes.isoformat(),
        "matches_at": (start - timedelta(days=1)).isoformat(),
        "capacity": 24,
    }


@contextmanager
def audit_store_fails():
    """Storage fault seam: the database refuses every new audit row."""
    with database_engine().begin() as connection:
        connection.execute(
            text("""CREATE FUNCTION audit_test_fail() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$""")
        )
        connection.execute(
            text("""CREATE TRIGGER audit_test_fault BEFORE INSERT ON operator_audit
            FOR EACH ROW EXECUTE FUNCTION audit_test_fail()""")
        )
    try:
        yield
    finally:
        with database_engine().begin() as connection:
            connection.execute(text("DROP TRIGGER audit_test_fault ON operator_audit"))
            connection.execute(text("DROP FUNCTION audit_test_fail()"))


def failing_operator():
    """An operator client that sees a server error as a response, not an exception."""
    client = TestClient(app, raise_server_exceptions=False)
    login(client, "operator")
    return client


def audit(client, **filters):
    response = client.get(AUDIT, params=filters)
    assert response.status_code == 200, response.text
    return response.json()["audit"]


def test_slot_creation_is_audited_once_and_only_operators_read_the_trail():
    with TestClient(app) as operator, TestClient(app) as member:
        login(operator, "operator")
        login(member)
        payload = slot_payload()
        created = send(operator, "POST", "/api/admin/event-slots", payload)
        assert created.status_code == 201, created.text
        slot_id = created.json()["event_slot"]["id"]
        assert member.get(AUDIT).status_code == 403
        rows = audit(operator)
        assert len(rows) == 1
        row = rows[0]
        assert row["actor"] == {"login_id": "operator"}
        assert (row["action"], row["target_type"], row["target_id"]) == (
            "event_slot.create",
            "event_slot",
            slot_id,
        )
        assert row["reason"] is None and row["before"] is None
        assert row["after"]["region_code"] == "hongdae"
        assert row["after"]["capacity"] == 24
        assert row["created_at"]
        # A rejected duplicate changes nothing and leaves no second row.
        assert send(operator, "POST", "/api/admin/event-slots", payload).status_code == 409
        assert len(audit(operator)) == 1


def test_a_slot_whose_audit_row_fails_is_not_created():
    with TestClient(app) as operator:
        login(operator, "operator")
        with audit_store_fails():
            failed = send(failing_operator(), "POST", "/api/admin/event-slots", slot_payload())
            assert failed.status_code >= 500
        assert operator.get("/api/admin/event-slots").json()["event_slots"] == []
        assert audit(operator) == []


def inventory_payload(slot_id):
    return {
        "event_slot_id": slot_id,
        "name": "감사 합성 식당",
        "address": "합성 주소",
        "map_url": "https://map.naver.com/",
        "price_krw": 15000,
        "capacity": 6,
    }


def test_inventory_registration_is_audited_and_rolls_back_with_its_audit_row():
    with TestClient(app) as operator:
        login(operator, "operator")
        created_slot = send(operator, "POST", "/api/admin/event-slots", slot_payload())
        slot_id = created_slot.json()["event_slot"]["id"]
        with audit_store_fails():
            failed = send(
                failing_operator(), "POST", "/api/admin/venue-inventory", inventory_payload(slot_id)
            )
            assert failed.status_code >= 500
        assert operator.get("/api/admin/venue-inventory").json()["inventory"] == []
        created = send(operator, "POST", "/api/admin/venue-inventory", inventory_payload(slot_id))
        assert created.status_code == 201, created.text
        inventory_id = created.json()["inventory"]["id"]
        rows = audit(operator, target_type="venue_inventory")
        assert [(r["action"], r["target_id"], r["actor"]["login_id"]) for r in rows] == [
            ("venue_inventory.create", inventory_id, "operator")
        ]
        assert rows[0]["before"] is None
        assert rows[0]["after"] == {
            "event_slot_id": slot_id,
            "name": "감사 합성 식당",
            "price_krw": 15000,
            "capacity": 6,
        }


@pytest.fixture
def seated():
    """Four confirmed members at one table, an inventory for its slot, and the operator."""
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, member in enumerate(members, 1):
            prepare(member, f"participant-0{index}")
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        created = send(operator, "POST", "/api/admin/venue-inventory", inventory_payload(slot))
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        table = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        yield {
            "operator": operator,
            "members": members,
            "ids": [member.get("/api/auth/me").json()["user"]["id"] for member in members],
            "slot": slot,
            "table": table,
            "inventory": created.json()["inventory"]["id"],
        }
    truncate("participant_sanction, safety_report, participant_exclusion")


def venue_state(member):
    return member.get("/api/me/gatherings").json()["gatherings"][0]["venue_state"]


def assert_no_private_text(rows):
    dumped = json.dumps(rows, ensure_ascii=False)
    for secret in ("010-0000-0000", "synthetic_demo", "합성 이름", "감사용 신고 원문"):
        assert secret not in dumped


def test_food_approval_and_no_show_review_are_audited_once_per_change(seated):
    operator, members, table = seated["operator"], seated["members"], seated["table"]
    path = f"/api/admin/venue-inventory/{seated['inventory']}/food-approvals"
    approval = {
        "dining_table_id": table["id"],
        "food_snapshot": table["food_snapshot"],
        "confirmed_suitable": True,
    }
    with audit_store_fails():
        assert send(failing_operator(), "POST", path, approval).status_code >= 500
    run_gathering_jobs()
    assert venue_state(members[0]) == "PENDING_OPERATOR"
    assert send(operator, "POST", path, approval).status_code == 200
    assert send(operator, "POST", path, approval).status_code == 200  # replay changes nothing
    run_gathering_jobs()
    assert venue_state(members[0]) == "ASSIGNED"
    rows = audit(operator, target_type="dining_table", target_id=table["id"])
    assert [(r["action"], r["actor"]["login_id"], r["before"]) for r in rows] == [
        ("venue_food.approve", "operator", None)
    ]
    assert rows[0]["after"] == {
        "inventory_id": seated["inventory"],
        "food_snapshot": table["food_snapshot"],
        "confirmed_suitable": True,
    }

    move_slot(seated["slot"], starts_in=-130, ends_in=-10)
    absent = seated["ids"][1]
    review = f"/api/admin/no-show-candidates/{table['id']}/{absent}"
    confirmed = {"decision": "CONFIRMED_NO_SHOW"}
    with audit_store_fails():
        assert send(failing_operator(), "POST", review, confirmed).status_code >= 500
    candidates = operator.get("/api/admin/no-show-candidates").json()["candidates"]
    assert absent in {item["user_id"] for item in candidates}
    assert send(operator, "POST", review, confirmed).status_code == 201
    assert send(operator, "POST", review, confirmed).status_code == 200
    assert send(operator, "POST", review, {"decision": "EXCUSED"}).status_code == 409
    rows = audit(operator, target_type="participant", target_id=absent)
    assert [(r["action"], r["actor"]["login_id"], r["before"]) for r in rows] == [
        ("no_show.review", "operator", None)
    ]
    assert rows[0]["after"] == {"dining_table_id": table["id"], "decision": "CONFIRMED_NO_SHOW"}
    assert_no_private_text(audit(operator))


def test_report_review_and_sanctions_are_audited_newest_first_per_target(seated):
    operator, members, ids = seated["operator"], seated["members"], seated["ids"]
    reported = ids[1]
    filed = send(
        members[0],
        "POST",
        "/api/me/reports",
        {
            "dining_table_id": seated["table"]["id"],
            "reported_id": reported,
            "reason_code": "harassment",
            "detail": "감사용 신고 원문",
        },
    )
    assert filed.status_code == 201, filed.text
    report_id = filed.json()["report"]["id"]
    review = f"/api/admin/reports/{report_id}/review"
    with audit_store_fails():
        assert (
            send(failing_operator(), "POST", review, {"decision": "CONFIRMED"}).status_code >= 500
        )
    assert operator.get("/api/admin/reports").json()["reports"][0]["state"] == "OPEN"
    assert send(operator, "POST", review, {"decision": "CONFIRMED"}).status_code == 200
    assert send(operator, "POST", review, {"decision": "CONFIRMED"}).status_code == 200
    rows = audit(operator, target_type="safety_report", target_id=report_id)
    assert [(r["action"], r["actor"]["login_id"]) for r in rows] == [("report.review", "operator")]
    assert (rows[0]["before"], rows[0]["after"]) == ({"state": "OPEN"}, {"state": "CONFIRMED"})

    warning = {"user_id": reported, "kind": "WARNING", "report_id": report_id}
    with audit_store_fails():
        assert send(failing_operator(), "POST", "/api/admin/sanctions", warning).status_code >= 500
    assert operator.get("/api/admin/sanctions").json()["sanctions"] == []
    first = send(operator, "POST", "/api/admin/sanctions", warning)
    assert first.status_code == 201, first.text
    assert send(operator, "POST", "/api/admin/sanctions", warning).status_code == 200
    ban = send(
        operator, "POST", "/api/admin/sanctions", {"user_id": reported, "kind": "PERMANENT_BAN"}
    )
    assert ban.status_code == 201, ban.text
    rows = audit(operator, target_type="participant", target_id=reported)
    assert [(r["action"], r["after"]["kind"]) for r in rows] == [
        ("sanction.create", "PERMANENT_BAN"),
        ("sanction.create", "WARNING"),
    ]
    assert rows[1]["after"] == {
        "sanction_id": first.json()["sanction"]["id"],
        "kind": "WARNING",
        "report_id": report_id,
        "ends_at": None,
    }
    assert [r["action"] for r in audit(operator, target_id=reported, limit=1)] == [
        "sanction.create"
    ]
    assert audit(operator, target_type="participant", target_id=ids[2]) == []
    everything = audit(operator)
    assert [r["action"] for r in everything] == [
        "sanction.create",
        "sanction.create",
        "report.review",
        "venue_inventory.create",
        "event_slot.create",
    ]
    assert operator.get(AUDIT, params={"limit": 0}).status_code == 422
    assert_no_private_text(everything)
