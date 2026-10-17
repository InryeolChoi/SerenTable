"""Work7 inventory and gathering behavior through HTTP and real PostgreSQL."""

import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from support import login, send, truncate
from test_applications import create_slot


@pytest.fixture(autouse=True)
def gathering_database(seeded_database):
    truncate("event_slot, participant_profile, consent_record, app_notification")


def test_operator_registers_inventory_and_participants_cannot_manage_it():
    with TestClient(app) as operator, TestClient(app) as member:
        login(operator, "operator")
        login(member)
        slot = create_slot(operator)
        payload = {
            "event_slot_id": slot,
            "name": "합성 식당",
            "address": "가상 주소",
            "map_url": "https://map.naver.com/",
            "price_krw": 15000,
            "capacity": 6,
        }
        assert send(member, "POST", "/api/admin/venue-inventory", payload).status_code == 403
        created = send(operator, "POST", "/api/admin/venue-inventory", payload)
        assert created.status_code == 201, created.text
        rows = operator.get("/api/admin/venue-inventory").json()["inventory"]
        assert rows[0]["id"] == created.json()["inventory"]["id"]
        assert member.get("/api/admin/venue-inventory").status_code == 403
        assert operator.post("/api/admin/venue-inventory", json=payload).status_code == 403


def test_unsafe_map_url_is_rejected_without_fetching_it():
    with TestClient(app) as operator:
        login(operator, "operator")
        slot = create_slot(operator)
        response = send(
            operator,
            "POST",
            "/api/admin/venue-inventory",
            {
                "event_slot_id": slot,
                "name": "합성 식당",
                "address": "가상 주소",
                "map_url": "javascript:alert(1)",
                "price_krw": 15000,
                "capacity": 6,
            },
        )
        assert response.status_code == 422


def test_unknown_food_is_an_exception_then_verified_inventory_allocates_once():
    import time
    from contextlib import ExitStack
    from serentable.gatherings import run_gathering_jobs
    from serentable.matching import run_due_matches
    from test_matching_runner import prepare, apply_and_pay, due_slot

    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, member in enumerate(members, 1):
            prepare(member, f"participant-0{i}")
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        created = send(
            operator,
            "POST",
            "/api/admin/venue-inventory",
            {
                "event_slot_id": slot,
                "name": "확인된 가상 식당",
                "address": "합성 주소",
                "map_url": "https://map.naver.com/",
                "price_krw": 15000,
                "capacity": 6,
            },
        )
        inventory = created.json()["inventory"]["id"]
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        run_gathering_jobs()
        mine = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        assert mine["venue_state"] == "PENDING_OPERATOR"
        assert mine["room_id"]
        assert len(members[0].get("/api/me/rooms").json()["rooms"]) == 1
        table = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        payload = {
            "dining_table_id": table["id"],
            "food_snapshot": table["food_snapshot"],
            "confirmed_suitable": True,
        }
        stale = {**payload, "food_snapshot": "0" * 64}
        path = f"/api/admin/venue-inventory/{inventory}/food-approvals"
        assert send(operator, "POST", path, stale).status_code == 409
        assert send(operator, "POST", path, payload).status_code == 200
        run_gathering_jobs()
        run_gathering_jobs()
        mine = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        assert mine["venue_state"] == "ASSIGNED"
        assert mine["venue"]["name"] == "확인된 가상 식당"
        messages = members[0].get(f"/api/me/rooms/{mine['room_id']}/messages").json()["messages"]
        assert len(messages) == 3  # confirmed, pending, assigned: no duplicate worker posts
        assert operator.get("/api/me/gatherings").status_code == 403
        assert members[0].get("/api/admin/gathering-tables").status_code == 403
